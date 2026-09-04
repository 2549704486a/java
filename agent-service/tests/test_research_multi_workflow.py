from __future__ import annotations

import threading
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from app.research.agents import EvidenceReviewRun, EvidenceReviewRunner, PlanningRun
from app.research.models import (
    CandidateAsset,
    CandidateBundle,
    ClaimEvidenceReview,
    EvidenceClaim,
    EvidenceReviewOutput,
    ResearchPlan,
    RunStatus,
    SourceDiscoveryMethod,
    SourceEvidence,
    SourceReadStatus,
    StageObservation,
    StageStatus,
    SupportStatus,
    load_research_brief,
)
from app.research.workflow import (
    IndependentResearcherRunner,
    MultiResearchWorkflow,
    ResearchTaskRun,
)
from app.research.web import FetchedPage


BRIEFS_DIR = Path(__file__).resolve().parents[1] / "research-data" / "briefs"


def completed_stage(name: str, *, tools: int = 0) -> StageObservation:
    now = datetime.now(timezone.utc)
    return StageObservation(
        stage=name,
        status=StageStatus.COMPLETED,
        started_at=now,
        completed_at=now,
        model_call_count=1,
        tool_call_count=tools,
        input_tokens=10,
        output_tokens=5,
    )


class FakePlanner:
    def __init__(self, plan: ResearchPlan) -> None:
        self.plan = plan

    def run(self, brief) -> PlanningRun:
        del brief
        return PlanningRun(
            plan=self.plan,
            stage=completed_stage("research-planning-agent"),
        )


class FakeParallelResearcher:
    def __init__(self, *, fail_task_id: str | None = None) -> None:
        self.fail_task_id = fail_task_id
        self.revised_task_ids: list[str] = []
        self._active = 0
        self.max_active = 0
        self._lock = threading.Lock()

    def run(self, brief, task) -> ResearchTaskRun:
        with self._lock:
            self._active += 1
            self.max_active = max(self.max_active, self._active)
        time.sleep(0.03)
        with self._lock:
            self._active -= 1
        if task.task_id == self.fail_task_id:
            raise RuntimeError("simulated researcher failure")
        return self._task_run(brief, task, revised=False)

    def revise(self, brief, task, feedback) -> ResearchTaskRun:
        self.revised_task_ids.append(task.task_id)
        self.assert_feedback(feedback)
        return self._task_run(brief, task, revised=True)

    @staticmethod
    def assert_feedback(feedback) -> None:
        if not feedback:
            raise AssertionError("revision feedback must not be empty")

    @staticmethod
    def _task_run(brief, task, *, revised: bool) -> ResearchTaskRun:
        source_id = f"source-{task.task_id}-page-001"
        candidate_id = f"candidate-{task.task_id}"
        source = SourceEvidence(
            source_id=source_id,
            url=f"https://example.com/{task.task_id}",
            title=f"Source for {task.task_id}",
            publisher="example.com",
            retrieved_at=datetime.now(timezone.utc),
            discovered_by=SourceDiscoveryMethod.AGENT_SEARCH,
            excerpt="Public evidence supports this candidate.",
            excerpt_ids=[f"{source_id}-excerpt-001"],
            read_status=SourceReadStatus.READABLE,
        )
        candidate = CandidateAsset(
            candidate_id=candidate_id,
            brief_id=brief.brief_id,
            brief_version=brief.version,
            asset_type=task.asset_types[0],
            name=f"Candidate {task.task_id}",
            summary="A public candidate supported by one readable source.",
            project_fit="This can be adapted after internal parameters are confirmed.",
            claims=[
                EvidenceClaim(
                    text="The public page supports this candidate fact.",
                    source_ids=[source_id],
                    support_status=SupportStatus.SUPPORTED,
                    review_note="Researcher extracted the readable source.",
                )
            ],
        )
        return ResearchTaskRun(
            task_id=task.task_id,
            bundle=CandidateBundle(
                brief_id=brief.brief_id,
                brief_version=brief.version,
                sources=[source],
                candidates=[candidate],
            ),
            stage=completed_stage(
                (
                    f"researcher-revision:{task.task_id}"
                    if revised
                    else f"researcher:{task.task_id}"
                ),
                tools=0 if revised else 1,
            ),
        )


class FakeReviewer:
    def __init__(
        self,
        *,
        first_partial_candidate: str | None = None,
        unknown_source: bool = False,
    ) -> None:
        self.first_partial_candidate = first_partial_candidate
        self.unknown_source = unknown_source
        self.call_count = 0

    def run(self, brief, bundle, *, stage_name="evidence-review-agent"):
        self.call_count += 1
        reviews = []
        for candidate in bundle.candidates:
            for claim_index, claim in enumerate(candidate.claims):
                is_first_partial = (
                    self.call_count == 1
                    and candidate.candidate_id == self.first_partial_candidate
                )
                reviews.append(
                    ClaimEvidenceReview(
                        candidate_id=candidate.candidate_id,
                        claim_index=claim_index,
                        source_ids=(
                            ["source-unknown-page-001"]
                            if self.unknown_source
                            else claim.source_ids
                        ),
                        support_status=(
                            SupportStatus.PARTIALLY_SUPPORTED
                            if is_first_partial
                            else SupportStatus.SUPPORTED
                        ),
                        review_note=(
                            "Evidence gap requires one focused revision."
                            if is_first_partial
                            else "The cited short evidence supports the claim."
                        ),
                    )
                )
        return EvidenceReviewRun(
            output=EvidenceReviewOutput(
                brief_id=brief.brief_id,
                brief_version=brief.version,
                reviews=reviews,
            ),
            stage=completed_stage(stage_name),
        )


class FakeReviewAgent:
    def __init__(self, output: EvidenceReviewOutput) -> None:
        self.output = output

    def invoke(self, inputs, config):
        del inputs, config
        return {"messages": [], "structured_response": self.output}


class IsolatedFakeWebClient:
    def __init__(self, registry: list["IsolatedFakeWebClient"]) -> None:
        self.fetch_calls: list[str] = []
        registry.append(self)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        del exc_type, exc_value, traceback

    def fetch(self, url: str) -> FetchedPage:
        self.fetch_calls.append(url)
        return FetchedPage(
            requested_url=url,
            final_url=url,
            title="Official source",
            publisher="example.com",
            text="Public evidence supports this candidate.",
            content_type="text/html",
            response_bytes=100,
            redirect_count=0,
        )


class SessionCollectionAgent:
    def __init__(self, session) -> None:
        self.session = session

    def invoke(self, inputs, config):
        del inputs, config
        self.session.tools[1].invoke({"url": "https://example.com/source"})
        return {"messages": []}


class SessionFinalizerAgent:
    def __init__(self, session) -> None:
        self.session = session

    def invoke(self, inputs, config):
        del inputs, config
        context = self.session.finalization_context()[0]
        source_id = context["source_id"]
        excerpt_id = next(iter(context["excerpt_options"]))
        asset_type = self.session.brief.targets[0].asset_type
        candidate_id = source_id.replace("source-", "candidate-", 1)
        return {
            "messages": [],
            "structured_response": {
                "brief_id": self.session.brief.brief_id,
                "brief_version": self.session.brief.version,
                "source_selections": [
                    {"source_id": source_id, "excerpt_id": excerpt_id}
                ],
                "candidates": [
                    {
                        "candidate_id": candidate_id,
                        "brief_id": self.session.brief.brief_id,
                        "brief_version": self.session.brief.version,
                        "asset_type": asset_type.value,
                        "name": f"Candidate {asset_type.value}",
                        "summary": "A public candidate supported by one source.",
                        "project_fit": "Internal business parameters still require confirmation.",
                        "claims": [
                            {
                                "text": "The public page supports this candidate fact.",
                                "source_ids": [source_id],
                                "support_status": "SUPPORTED",
                                "review_note": "The page directly supports the claim.",
                            }
                        ],
                    }
                ],
            },
        }


class MultiResearchWorkflowTest(unittest.TestCase):
    def setUp(self) -> None:
        self.brief = load_research_brief(BRIEFS_DIR / "pilot-mixed-v1.json")
        self.plan = ResearchPlan.model_validate(
            {
                "brief_id": self.brief.brief_id,
                "brief_version": self.brief.version,
                "tasks": [
                    {
                        "task_id": "task-award",
                        "focus_key": "award-focus",
                        "objective": "Research one public award candidate source.",
                        "asset_types": ["AWARD_CANDIDATE"],
                        "target_count": 1,
                        "search_queries": ["official product specs"],
                        "source_urls": [
                            "https://www.mi.com/global/product/xiaomi-smart-band-9/specs/"
                        ],
                        "max_pages": 2,
                    },
                    {
                        "task_id": "task-campaign",
                        "focus_key": "campaign-focus",
                        "objective": "Research one public campaign pattern source.",
                        "asset_types": ["CAMPAIGN_PATTERN"],
                        "target_count": 1,
                        "search_queries": ["official rewards terms"],
                        "source_urls": [
                            "https://www.starbucks.com/rewards/terms/"
                        ],
                        "max_pages": 2,
                    },
                    {
                        "task_id": "task-segment",
                        "focus_key": "segment-focus",
                        "objective": "Research one computable segment rule source.",
                        "asset_types": ["SEGMENT_RULE_TEMPLATE"],
                        "target_count": 1,
                        "search_queries": ["official RFM documentation"],
                        "source_urls": [
                            "https://documentation.bloomreach.com/engagement/docs/rfm-segmentation"
                        ],
                        "max_pages": 2,
                    },
                ],
            }
        )

    def run_workflow(self, researcher, reviewer):
        return MultiResearchWorkflow(
            FakePlanner(self.plan),
            researcher,
            reviewer,
        ).run(
            self.brief,
            experiment_id="experiment-pilot",
            run_id="project-multi-run-001",
        )

    def test_parallel_tasks_merge_and_record_each_stage_usage(self):
        researcher = FakeParallelResearcher()
        run = self.run_workflow(researcher, FakeReviewer())

        self.assertGreaterEqual(researcher.max_active, 2)
        self.assertEqual(RunStatus.COMPLETED, run.summary.status)
        self.assertEqual(3, len(run.bundle.candidates))
        self.assertEqual(5, sum(stage.model_call_count for stage in run.summary.stages))
        self.assertEqual(3, sum(stage.tool_call_count for stage in run.summary.stages))
        self.assertTrue(all(run.gate_report.approvable_candidate_ids))

    def test_parallel_failure_is_located_without_losing_other_results(self):
        run = self.run_workflow(
            FakeParallelResearcher(fail_task_id="task-campaign"),
            FakeReviewer(),
        )

        self.assertEqual(RunStatus.INCOMPLETE, run.summary.status)
        self.assertEqual("parallel-research", run.summary.failure_stage)
        failed = [
            stage for stage in run.summary.stages if stage.status == StageStatus.FAILED
        ]
        self.assertEqual("researcher:task-campaign", failed[0].stage)
        self.assertEqual(2, len(run.bundle.candidates))

    def test_empty_task_result_marks_run_incomplete_without_losing_candidates(self):
        researcher = FakeParallelResearcher()
        original_run = researcher.run

        def run_without_campaign(brief, task):
            result = original_run(brief, task)
            if task.task_id != "task-campaign":
                return result
            bundle_payload = result.bundle.model_dump(mode="python")
            bundle_payload["candidates"] = []
            return ResearchTaskRun(
                task_id=result.task_id,
                bundle=CandidateBundle.model_validate(bundle_payload),
                stage=result.stage.model_copy(update={"output_candidate_ids": []}),
            )

        researcher.run = run_without_campaign
        run = self.run_workflow(researcher, FakeReviewer())

        self.assertEqual(RunStatus.INCOMPLETE, run.summary.status)
        self.assertEqual("target-completion", run.summary.failure_stage)
        self.assertEqual(2, len(run.bundle.candidates))
        self.assertTrue(
            any(
                issue.code == "TARGET_COUNT_NOT_MET"
                for issue in run.gate_report.run_issues
            )
        )

    def test_only_affected_researcher_is_revised_once(self):
        researcher = FakeParallelResearcher()
        reviewer = FakeReviewer(
            first_partial_candidate="candidate-task-award"
        )
        run = self.run_workflow(researcher, reviewer)

        self.assertEqual(["task-award"], researcher.revised_task_ids)
        self.assertEqual(2, reviewer.call_count)
        self.assertEqual(
            1,
            sum(
                stage.stage.startswith("researcher-revision:")
                for stage in run.summary.stages
            ),
        )
        self.assertIn(
            "candidate-task-award",
            run.gate_report.approvable_candidate_ids,
        )

    def test_reviewer_cannot_override_unknown_source_gate(self):
        run = self.run_workflow(
            FakeParallelResearcher(),
            FakeReviewer(unknown_source=True),
        )

        self.assertEqual([], run.gate_report.approvable_candidate_ids)
        self.assertEqual(3, len(run.gate_report.rejected_candidate_ids))
        self.assertTrue(
            all(
                any(issue.code == "UNKNOWN_SOURCE_REFERENCE" for issue in decision.issues)
                for decision in run.gate_report.decisions
            )
        )

    def test_evidence_review_runner_requires_exact_claim_coverage(self):
        task = self.plan.tasks[0]
        bundle = FakeParallelResearcher._task_run(
            self.brief,
            task,
            revised=False,
        ).bundle
        complete_output = EvidenceReviewOutput(
            brief_id=self.brief.brief_id,
            brief_version=self.brief.version,
            reviews=[
                ClaimEvidenceReview(
                    candidate_id="candidate-task-award",
                    claim_index=0,
                    source_ids=["source-task-award-page-001"],
                    support_status=SupportStatus.SUPPORTED,
                    review_note="The short evidence supports the claim.",
                )
            ],
        )

        review_run = EvidenceReviewRunner(FakeReviewAgent(complete_output)).run(
            self.brief,
            bundle,
        )
        self.assertEqual(0, review_run.stage.tool_call_count)

        incomplete_output = complete_output.model_copy(update={"reviews": []})
        with self.assertRaisesRegex(ValueError, "未逐条覆盖"):
            EvidenceReviewRunner(FakeReviewAgent(incomplete_output)).run(
                self.brief,
                bundle,
            )

    def test_concrete_researcher_isolates_sessions_and_revision_has_no_web_call(self):
        clients: list[IsolatedFakeWebClient] = []

        def web_factory():
            return IsolatedFakeWebClient(clients)

        def agent_factory(settings, session):
            del settings
            return SessionCollectionAgent(session), SessionFinalizerAgent(session)

        researcher = IndependentResearcherRunner(
            object(),  # type: ignore[arg-type]
            web_client_factory=web_factory,
        )
        with patch(
            "app.research.workflow.build_single_research_agents",
            side_effect=agent_factory,
        ):
            award_run = researcher.run(self.brief, self.plan.tasks[0])
            campaign_run = researcher.run(self.brief, self.plan.tasks[1])
            revised_run = researcher.revise(
                self.brief,
                self.plan.tasks[0],
                [{"review_note": "Use the existing evidence more precisely."}],
            )

        self.assertEqual(2, len(clients))
        self.assertEqual(2, sum(len(client.fetch_calls) for client in clients))
        self.assertNotEqual(
            award_run.bundle.sources[0].source_id,
            campaign_run.bundle.sources[0].source_id,
        )
        self.assertTrue(
            award_run.bundle.sources[0].source_id.startswith(
                "source-task-award-page-"
            )
        )
        self.assertEqual(0, revised_run.stage.tool_call_count)


if __name__ == "__main__":
    unittest.main()
