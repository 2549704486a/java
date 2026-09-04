from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from threading import Lock
from typing import Any, Callable, Protocol

from app.config import Settings
from app.research.agents import (
    EvidenceReviewRun,
    PlanningRun,
    ResearchToolSession,
    SingleResearchRunner,
    build_single_research_agents,
    read_model_usage,
)
from app.research.gates import evaluate_candidate_bundle
from app.research.models import (
    CandidateBundle,
    EvidenceReviewOutput,
    ExperimentArm,
    GateReport,
    ResearchAgentOutput,
    ResearchBrief,
    ResearchPlan,
    ResearchTask,
    RunStatus,
    RunSummary,
    StageObservation,
    StageStatus,
    SupportStatus,
)
from app.research.web import PublicWebClient


@dataclass(frozen=True)
class ResearchTaskRun:
    task_id: str
    bundle: CandidateBundle
    stage: StageObservation


@dataclass(frozen=True)
class MultiResearchRun:
    plan: ResearchPlan
    bundle: CandidateBundle
    gate_report: GateReport
    summary: RunSummary
    review: EvidenceReviewOutput | None


@dataclass(frozen=True)
class _ResearcherState:
    task_brief: ResearchBrief
    session: ResearchToolSession
    finalizer: Any
    bundle: CandidateBundle


class PlanningRunner(Protocol):
    def run(self, brief: ResearchBrief) -> PlanningRun: ...


class ResearcherRunner(Protocol):
    def run(self, brief: ResearchBrief, task: ResearchTask) -> ResearchTaskRun: ...

    def revise(
        self,
        brief: ResearchBrief,
        task: ResearchTask,
        feedback: list[dict[str, object]],
    ) -> ResearchTaskRun: ...


class ReviewRunner(Protocol):
    def run(
        self,
        brief: ResearchBrief,
        bundle: CandidateBundle,
        *,
        stage_name: str = "evidence-review-agent",
    ) -> EvidenceReviewRun: ...


class IndependentResearcherRunner:
    """Creates one isolated Agent context and web session per planned task."""

    def __init__(
        self,
        settings: Settings,
        *,
        web_client_factory: Callable[[], Any] = PublicWebClient,
    ) -> None:
        self._settings = settings
        self._web_client_factory = web_client_factory
        self._states: dict[str, _ResearcherState] = {}
        self._state_lock = Lock()

    def run(self, brief: ResearchBrief, task: ResearchTask) -> ResearchTaskRun:
        task_brief = _build_task_brief(brief, task)
        with self._web_client_factory() as web_client:
            session = ResearchToolSession(
                task_brief,
                web_client,
                source_namespace=f"{task.task_id}-page",
                search_limit=len(task.search_queries),
                read_limit=task.max_pages,
            )
            collector, finalizer = build_single_research_agents(
                self._settings,
                session,
            )
            single_run = SingleResearchRunner(
                collector,
                session,
                finalizer=finalizer,
            ).run(
                task_brief,
                experiment_id="multi-task-research",
                run_id=f"task-run-{task.task_id}",
            )
        stage_payload = single_run.summary.stages[0].model_dump(mode="python")
        stage_payload["stage"] = f"researcher:{task.task_id}"
        stage = StageObservation.model_validate(stage_payload)
        with self._state_lock:
            self._states[task.task_id] = _ResearcherState(
                task_brief=task_brief,
                session=session,
                finalizer=finalizer,
                bundle=single_run.bundle,
            )
        return ResearchTaskRun(
            task_id=task.task_id,
            bundle=single_run.bundle,
            stage=stage,
        )

    def revise(
        self,
        brief: ResearchBrief,
        task: ResearchTask,
        feedback: list[dict[str, object]],
    ) -> ResearchTaskRun:
        del brief
        with self._state_lock:
            state = self._states.get(task.task_id)
        if state is None:
            raise ValueError(f"研究任务没有可返修的原始上下文：{task.task_id}")

        started_at = datetime.now(timezone.utc)
        result = state.finalizer.invoke(
            {
                "messages": [
                    {
                        "role": "user",
                        "content": (
                            "根据证据审核反馈返修当前任务候选。不得调用 Tool、不得新增来源，"
                            "候选 ID 集合必须保持不变；证据不足时如实降级状态。\n"
                            "任务："
                            + json.dumps(task.model_dump(mode="json"), ensure_ascii=False)
                            + "\n审核反馈："
                            + json.dumps(feedback, ensure_ascii=False)
                            + "\n原候选："
                            + json.dumps(
                                state.bundle.model_dump(mode="json"),
                                ensure_ascii=False,
                            )
                            + "\n可用短证据："
                            + json.dumps(
                                state.session.finalization_context(),
                                ensure_ascii=False,
                            )
                        ),
                    }
                ]
            },
            config={"recursion_limit": 8},
        )
        output = ResearchAgentOutput.model_validate(result.get("structured_response"))
        revised_bundle = state.session.materialize_bundle(output)
        original_ids = {
            candidate.candidate_id for candidate in state.bundle.candidates
        }
        revised_ids = {
            candidate.candidate_id for candidate in revised_bundle.candidates
        }
        if revised_ids != original_ids:
            raise ValueError("研究返修改变了候选 ID 集合")
        completed_at = datetime.now(timezone.utc)
        model_calls, input_tokens, output_tokens = read_model_usage(result)
        stage = StageObservation(
            stage=f"researcher-revision:{task.task_id}",
            status=StageStatus.COMPLETED,
            started_at=started_at,
            completed_at=completed_at,
            model_call_count=model_calls,
            tool_call_count=0,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            retry_count=1,
            output_candidate_ids=sorted(revised_ids),
        )
        with self._state_lock:
            self._states[task.task_id] = _ResearcherState(
                task_brief=state.task_brief,
                session=state.session,
                finalizer=state.finalizer,
                bundle=revised_bundle,
            )
        return ResearchTaskRun(
            task_id=task.task_id,
            bundle=revised_bundle,
            stage=stage,
        )


class MultiResearchWorkflow:
    """Runs a fixed plan, parallel research, review, optional revision, and gate."""

    def __init__(
        self,
        planner: PlanningRunner,
        researcher: ResearcherRunner,
        reviewer: ReviewRunner,
    ) -> None:
        self._planner = planner
        self._researcher = researcher
        self._reviewer = reviewer

    def run(
        self,
        brief: ResearchBrief,
        *,
        experiment_id: str,
        run_id: str,
    ) -> MultiResearchRun:
        started_at = datetime.now(timezone.utc)
        planning = self._planner.run(brief)
        stages = [planning.stage]
        task_runs, failed_task_ids, failure_stages = self._run_tasks(
            brief,
            planning.plan.tasks,
            revised=False,
        )
        incomplete_task_ids = _find_incomplete_task_ids(
            planning.plan.tasks,
            task_runs,
        )
        stages.extend(
            stage
            for task in planning.plan.tasks
            for stage in failure_stages + [
                run.stage for run in task_runs if run.task_id == task.task_id
            ]
            if _stage_matches_task(stage, task.task_id)
        )

        merged = _merge_task_bundles(brief, task_runs)
        review_run = self._reviewer.run(brief, merged)
        stages.append(review_run.stage)
        reviewed_bundle = _apply_review(brief, merged, review_run.output)
        final_review = review_run.output

        revision_feedback = _revision_feedback(review_run.output)
        if revision_feedback and brief.budget.max_revision_rounds > 0:
            candidate_tasks = _candidate_task_map(task_runs)
            affected_task_ids = {
                candidate_tasks[candidate_id]
                for candidate_id in revision_feedback
                if candidate_id in candidate_tasks
            }
            feedback_by_task: dict[str, list[dict[str, object]]] = {}
            for candidate_id, items in revision_feedback.items():
                task_id = candidate_tasks.get(candidate_id)
                if task_id is not None:
                    feedback_by_task.setdefault(task_id, []).extend(items)
            revision_tasks = [
                task
                for task in planning.plan.tasks
                if task.task_id in affected_task_ids
            ]
            revised_runs, revision_failures, revision_failure_stages = (
                self._run_tasks(
                    brief,
                    revision_tasks,
                    revised=True,
                    feedback_by_task=feedback_by_task,
                )
            )
            failed_task_ids.update(revision_failures)
            stages.extend(revision_failure_stages)
            stages.extend(run.stage for run in revised_runs)
            task_runs = _replace_task_runs(task_runs, revised_runs)
            merged = _merge_task_bundles(brief, task_runs)
            second_review = self._reviewer.run(
                brief,
                merged,
                stage_name="evidence-review-agent-after-revision",
            )
            stages.append(second_review.stage)
            reviewed_bundle = _apply_review(brief, merged, second_review.output)
            final_review = second_review.output

        gate_report = evaluate_candidate_bundle(brief, reviewed_bundle)
        completed_at = datetime.now(timezone.utc)
        incomplete_task_ids.update(failed_task_ids)
        status = (
            RunStatus.INCOMPLETE
            if incomplete_task_ids
            else RunStatus.COMPLETED
        )
        failure_stage = None
        if failed_task_ids:
            failure_stage = "parallel-research"
        elif incomplete_task_ids:
            failure_stage = "target-completion"
        return MultiResearchRun(
            plan=planning.plan,
            bundle=reviewed_bundle,
            gate_report=gate_report,
            review=final_review,
            summary=RunSummary(
                experiment_id=experiment_id,
                run_id=run_id,
                brief_id=brief.brief_id,
                brief_version=brief.version,
                run_kind=brief.run_kind,
                arm=ExperimentArm.PROJECT_MULTI,
                status=status,
                started_at=started_at,
                completed_at=completed_at,
                stages=stages,
                failure_stage=failure_stage,
            ),
        )

    def _run_tasks(
        self,
        brief: ResearchBrief,
        tasks: list[ResearchTask],
        *,
        revised: bool,
        feedback_by_task: dict[str, list[dict[str, object]]] | None = None,
    ) -> tuple[list[ResearchTaskRun], set[str], list[StageObservation]]:
        if not tasks:
            return [], set(), []
        runs: list[ResearchTaskRun] = []
        failed_task_ids: set[str] = set()
        failure_stages: list[StageObservation] = []
        with ThreadPoolExecutor(max_workers=len(tasks)) as executor:
            futures = {}
            for task in tasks:
                if revised:
                    feedback = (feedback_by_task or {}).get(task.task_id, [])
                    future = executor.submit(
                        self._researcher.revise,
                        brief,
                        task,
                        feedback,
                    )
                else:
                    future = executor.submit(self._researcher.run, brief, task)
                futures[future] = task

            for future in as_completed(futures):
                task = futures[future]
                try:
                    run = future.result()
                    if run.task_id != task.task_id:
                        raise ValueError("研究执行结果引用了错误的任务 ID")
                    runs.append(run)
                except Exception as exc:
                    failed_task_ids.add(task.task_id)
                    now = datetime.now(timezone.utc)
                    failure_stages.append(
                        StageObservation(
                            stage=(
                                f"researcher-revision:{task.task_id}"
                                if revised
                                else f"researcher:{task.task_id}"
                            ),
                            status=StageStatus.FAILED,
                            started_at=now,
                            completed_at=now,
                            error_category=exc.__class__.__name__,
                        )
                    )
        order = {task.task_id: index for index, task in enumerate(tasks)}
        runs.sort(key=lambda run: order[run.task_id])
        failure_stages.sort(key=lambda stage: stage.stage)
        return runs, failed_task_ids, failure_stages


def _merge_task_bundles(
    brief: ResearchBrief,
    task_runs: list[ResearchTaskRun],
) -> CandidateBundle:
    for run in task_runs:
        if (run.bundle.brief_id, run.bundle.brief_version) != (
            brief.brief_id,
            brief.version,
        ):
            raise ValueError(f"研究任务 {run.task_id} 返回了错误的简报版本")
    return CandidateBundle(
        brief_id=brief.brief_id,
        brief_version=brief.version,
        sources=[source for run in task_runs for source in run.bundle.sources],
        candidates=[
            candidate for run in task_runs for candidate in run.bundle.candidates
        ],
    )


def _apply_review(
    brief: ResearchBrief,
    bundle: CandidateBundle,
    review: EvidenceReviewOutput,
) -> CandidateBundle:
    if (review.brief_id, review.brief_version) != (
        brief.brief_id,
        brief.version,
    ):
        raise ValueError("证据审核结果引用了错误的简报版本")
    review_by_key = {
        (item.candidate_id, item.claim_index): item for item in review.reviews
    }
    expected_keys = {
        (candidate.candidate_id, index)
        for candidate in bundle.candidates
        for index, _ in enumerate(candidate.claims)
    }
    if set(review_by_key) != expected_keys:
        raise ValueError("证据审核结果没有逐条覆盖当前候选")

    reviewed_candidates = []
    for candidate in bundle.candidates:
        claims = []
        for index, claim in enumerate(candidate.claims):
            item = review_by_key[(candidate.candidate_id, index)]
            claim_payload = claim.model_dump(mode="python")
            claim_payload.update(
                {
                    "source_ids": item.source_ids,
                    "support_status": item.support_status,
                    "review_note": item.review_note,
                }
            )
            claims.append(claim.__class__.model_validate(claim_payload))
        candidate_payload = candidate.model_dump(mode="python")
        candidate_payload["claims"] = claims
        reviewed_candidates.append(
            candidate.__class__.model_validate(candidate_payload)
        )
    bundle_payload = bundle.model_dump(mode="python")
    bundle_payload["candidates"] = reviewed_candidates
    return CandidateBundle.model_validate(bundle_payload)


def _revision_feedback(
    review: EvidenceReviewOutput,
) -> dict[str, list[dict[str, object]]]:
    feedback: dict[str, list[dict[str, object]]] = {}
    for item in review.reviews:
        if item.support_status == SupportStatus.SUPPORTED:
            continue
        feedback.setdefault(item.candidate_id, []).append(
            {
                "candidate_id": item.candidate_id,
                "claim_index": item.claim_index,
                "support_status": item.support_status.value,
                "review_note": item.review_note,
            }
        )
    return feedback


def _candidate_task_map(task_runs: list[ResearchTaskRun]) -> dict[str, str]:
    return {
        candidate.candidate_id: run.task_id
        for run in task_runs
        for candidate in run.bundle.candidates
    }


def _find_incomplete_task_ids(
    tasks: list[ResearchTask],
    task_runs: list[ResearchTaskRun],
) -> set[str]:
    runs_by_task = {run.task_id: run for run in task_runs}
    incomplete: set[str] = set()
    for task in tasks:
        run = runs_by_task.get(task.task_id)
        if run is None:
            incomplete.add(task.task_id)
            continue
        asset_type = task.asset_types[0]
        actual_count = sum(
            candidate.asset_type == asset_type
            for candidate in run.bundle.candidates
        )
        if actual_count < task.target_count:
            incomplete.add(task.task_id)
    return incomplete


def _replace_task_runs(
    original: list[ResearchTaskRun],
    revised: list[ResearchTaskRun],
) -> list[ResearchTaskRun]:
    revised_by_task = {run.task_id: run for run in revised}
    return [revised_by_task.get(run.task_id, run) for run in original]


def _stage_matches_task(stage: StageObservation, task_id: str) -> bool:
    return stage.stage.endswith(f":{task_id}")


def _build_task_brief(
    brief: ResearchBrief,
    task: ResearchTask,
) -> ResearchBrief:
    asset_type = task.asset_types[0]
    source_target = next(
        target for target in brief.targets if target.asset_type == asset_type
    )
    target_payload = source_target.model_dump(mode="python")
    target_payload["target_count"] = task.target_count
    brief_payload = brief.model_dump(mode="python")
    brief_payload.update(
        {
            "objective": task.objective,
            "targets": [target_payload],
            "explicit_source_urls": task.source_urls,
            "source_requirements": [
                *brief.source_requirements,
                "优先使用规划查询：" + "；".join(task.search_queries),
            ][:10],
            "budget": {
                **brief.budget.model_dump(mode="python"),
                "max_search_queries": len(task.search_queries),
                "max_pages_to_read": task.max_pages,
                "max_parallel_tasks": 1,
                "max_revision_rounds": 0,
            },
            "output_label": f"{brief.output_label}-{task.task_id}"[:80],
        }
    )
    return ResearchBrief.model_validate(brief_payload)
