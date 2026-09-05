from __future__ import annotations

import random
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Iterable

from app.research.artifacts import ResearchRunStore
from app.research.gates import evaluate_candidate_bundle
from app.research.models import (
    BlindMapping,
    BlindMappingEntry,
    BlindMaterial,
    BlindPackage,
    BlindQualityMetrics,
    BlindScoreRecord,
    BlindScoreSubmission,
    CandidateBundle,
    ComparisonReport,
    EvaluationInputManifest,
    EvaluationRunRecord,
    EvaluationRunReference,
    ExperimentArm,
    ExperimentPolicy,
    ExternalRunPayload,
    FailedRunArtifact,
    GateReport,
    LockedScoreSet,
    ResearchBrief,
    RetentionRecommendation,
    RevealedRunResult,
    RunEvaluationMetrics,
    RunKind,
    RunStatus,
    RunSummary,
    SourceReadStatus,
    SupportStatus,
)


_OFFICIAL_BRIEF_FILE = re.compile(r"^(?P<brief_id>[a-z0-9-]+)-(?P<version>v[1-9][0-9]*)\.json$")


def import_external_run(
    payload: ExternalRunPayload,
    store: ResearchRunStore,
    expected_brief: ResearchBrief,
) -> EvaluationRunRecord:
    if payload.summary.arm not in {
        ExperimentArm.CODEX_DIRECT,
        ExperimentArm.CODEX_DELEGATED,
    }:
        raise ValueError("外部导入只接受两个 Codex 执行臂")
    if payload.summary.run_kind != RunKind.OFFICIAL:
        raise ValueError("外部执行臂只能导入正式运行")
    if payload.brief != expected_brief:
        raise ValueError("外部结果携带的简报与仓库冻结正式简报不一致")

    gate_report = evaluate_candidate_bundle(payload.brief, payload.bundle)
    record = EvaluationRunRecord(
        brief=payload.brief,
        bundle=payload.bundle,
        summary=payload.summary,
        gate_report=gate_report,
    )
    run_directory = store.create_run_directory(
        experiment_id=payload.summary.experiment_id,
        arm=payload.summary.arm.value,
        run_id=payload.summary.run_id,
    )
    store.write_json_once(run_directory, "brief.json", record.brief)
    store.write_json_once(run_directory, "bundle.json", record.bundle)
    store.write_json_once(run_directory, "summary.json", record.summary)
    store.write_json_once(run_directory, "gate-report.json", record.gate_report)
    return record


def load_evaluation_run(run_directory: str | Path) -> EvaluationRunRecord:
    directory = Path(run_directory)
    brief = ResearchBrief.model_validate(_read_json(directory / "brief.json"))
    complete_files = [
        directory / "bundle.json",
        directory / "summary.json",
        directory / "gate-report.json",
    ]
    if all(path.is_file() for path in complete_files):
        return EvaluationRunRecord.model_validate(
            {
                "brief": brief,
                "bundle": _read_json(complete_files[0]),
                "summary": _read_json(complete_files[1]),
                "gate_report": _read_json(complete_files[2]),
            }
        )
    if any(path.is_file() for path in complete_files):
        raise ValueError("运行目录只包含部分完成产物，不能进入正式评估")

    failure_path = directory / "failure.json"
    if not failure_path.is_file():
        raise ValueError("运行目录既没有完整结果，也没有失败产物")
    failure = FailedRunArtifact.model_validate(_read_json(failure_path))
    if (failure.brief_id, failure.brief_version) != (
        brief.brief_id,
        brief.version,
    ):
        raise ValueError("失败产物与运行简报版本不一致")
    bundle = CandidateBundle(
        brief_id=brief.brief_id,
        brief_version=brief.version,
    )
    summary = RunSummary(
        experiment_id=failure.experiment_id,
        run_id=failure.run_id,
        brief_id=failure.brief_id,
        brief_version=failure.brief_version,
        run_kind=brief.run_kind,
        arm=failure.arm,
        status=RunStatus.FAILED,
        started_at=failure.started_at,
        completed_at=failure.completed_at,
        failure_stage=failure.failure_stage,
    )
    return EvaluationRunRecord(
        brief=brief,
        bundle=bundle,
        summary=summary,
        gate_report=evaluate_candidate_bundle(brief, bundle),
    )


def build_evaluation_manifest(
    policy: ExperimentPolicy,
    records: Iterable[EvaluationRunRecord],
    *,
    created_at: datetime,
) -> EvaluationInputManifest:
    records_by_key = _index_records(policy, records)
    expected_keys = _expected_run_keys(policy)
    if set(records_by_key) != expected_keys:
        missing = sorted(
            expected_keys - records_by_key.keys(),
            key=lambda item: (item[0].value, item[1]),
        )
        unexpected = sorted(
            records_by_key.keys() - expected_keys,
            key=lambda item: (item[0].value, item[1]),
        )
        raise ValueError(
            f"正式评估必须锁定全部十二个运行；缺少 {missing}，越界 {unexpected}"
        )
    return EvaluationInputManifest(
        experiment_id=policy.experiment_id,
        policy_version=policy.version,
        created_at=created_at,
        runs=[
            EvaluationRunReference(
                arm=arm,
                brief_id=brief_id,
                brief_version=record.brief.version,
                run_id=record.summary.run_id,
            )
            for (arm, brief_id), record in sorted(
                records_by_key.items(),
                key=lambda item: (item[0][0].value, item[0][1]),
            )
        ],
    )


def persist_blind_evaluation(
    store: ResearchRunStore,
    policy: ExperimentPolicy,
    evaluation_id: str,
    manifest: EvaluationInputManifest,
    mapping: BlindMapping,
    package: BlindPackage,
) -> Path:
    _validate_mapping(policy, mapping)
    if (
        package.experiment_id != policy.experiment_id
        or package.policy_version != policy.version
    ):
        raise ValueError("匿名评分材料与实验策略不一致")
    if (
        manifest.experiment_id != policy.experiment_id
        or manifest.policy_version != policy.version
    ):
        raise ValueError("评估输入清单与实验策略不一致")
    evaluation_directory = store.create_evaluation_directory(
        experiment_id=policy.experiment_id,
        evaluation_id=evaluation_id,
    )
    store.write_json_once(evaluation_directory, "blind-package.json", package)
    store.write_json_once(evaluation_directory, "blind-mapping.json", mapping)
    store.write_json_once(evaluation_directory, "evaluation-input.json", manifest)
    store.write_json_once(
        evaluation_directory,
        "score-sheet-template.json",
        build_score_sheet_template(package),
    )
    store.write_text_once(
        evaluation_directory,
        "blind-review.md",
        render_blind_review(package),
    )
    return evaluation_directory


def persist_locked_scores(
    store: ResearchRunStore,
    evaluation_directory: str | Path,
    locked_scores: LockedScoreSet,
) -> Path:
    return store.write_json_once(
        evaluation_directory,
        "locked-scores.json",
        locked_scores,
    )


def persist_comparison_report(
    store: ResearchRunStore,
    evaluation_directory: str | Path,
    report: ComparisonReport,
) -> Path:
    return store.write_json_once(
        evaluation_directory,
        "comparison-report.json",
        report,
    )


def calculate_run_metrics(record: EvaluationRunRecord) -> RunEvaluationMetrics:
    target_counts = {
        target.asset_type: target.target_count for target in record.brief.targets
    }
    actual_counts = Counter(
        candidate.asset_type for candidate in record.bundle.candidates
    )
    target_count = sum(target_counts.values())
    completed_count = sum(
        min(actual_counts[asset_type], expected)
        for asset_type, expected in target_counts.items()
    )
    readable_source_ids = {
        source.source_id
        for source in record.bundle.sources
        if source.read_status == SourceReadStatus.READABLE
    }
    claims = [
        claim
        for candidate in record.bundle.candidates
        for claim in candidate.claims
    ]
    traceable_claim_count = sum(
        bool(claim.source_ids)
        and set(claim.source_ids).issubset(readable_source_ids)
        for claim in claims
    )
    conflict_claim_count = sum(
        claim.support_status == SupportStatus.CONFLICTING for claim in claims
    )
    unsupported_claim_count = sum(
        claim.support_status == SupportStatus.UNSUPPORTED for claim in claims
    )
    evidence_supported_candidate_count = sum(
        all(
            claim.support_status == SupportStatus.SUPPORTED
            and bool(claim.source_ids)
            and set(claim.source_ids).issubset(readable_source_ids)
            for claim in candidate.claims
        )
        for candidate in record.bundle.candidates
    )
    duplicate_candidate_ids = {
        decision.candidate_id
        for decision in record.gate_report.decisions
        if any(
            issue.code in {"DUPLICATE_CANDIDATE", "DUPLICATE_CANDIDATE_ID"}
            for issue in decision.issues
        )
    }
    stages = record.summary.stages
    input_tokens = _sum_known(stage.input_tokens for stage in stages)
    output_tokens = _sum_known(stage.output_tokens for stage in stages)
    elapsed_delta = (
        record.summary.completed_at - record.summary.started_at
    ).total_seconds()
    elapsed_seconds = elapsed_delta if elapsed_delta > 0 else None

    return RunEvaluationMetrics(
        brief_id=record.brief.brief_id,
        brief_version=record.brief.version,
        arm=record.summary.arm,
        status=record.summary.status,
        target_count=target_count,
        candidate_count=len(record.bundle.candidates),
        target_completion=completed_count / target_count,
        readable_source_count=len(readable_source_ids),
        traceable_claim_rate=(
            traceable_claim_count / len(claims) if claims else None
        ),
        evidence_supported_candidate_count=evidence_supported_candidate_count,
        approvable_candidate_count=len(record.gate_report.approvable_candidate_ids),
        explicit_conflict_claim_rate=(
            conflict_claim_count / len(claims) if claims else None
        ),
        unsupported_claim_count=unsupported_claim_count,
        duplicate_candidate_count=len(duplicate_candidate_ids),
        run_issue_count=len(record.gate_report.run_issues),
        gate_failed_candidate_count=len(record.gate_report.rejected_candidate_ids),
        elapsed_seconds=elapsed_seconds,
        model_call_count=_sum_known(stage.model_call_count for stage in stages),
        tool_call_count=_sum_known(stage.tool_call_count for stage in stages),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        retry_count=sum(stage.retry_count for stage in stages),
        failure_stage=record.summary.failure_stage,
    )


def build_score_sheet_template(package: BlindPackage) -> dict:
    return {
        "experiment_id": package.experiment_id,
        "policy_version": package.policy_version,
        "scorer": None,
        "records": [
            {
                "blind_label": material.blind_label,
                "brief_id": material.brief_id,
                "project_relevance": None,
                "factual_support": None,
                "adaptation_usability": None,
                "conflict_handling": None,
                "notes": None,
            }
            for material in package.materials
        ],
    }


def render_blind_review(package: BlindPackage) -> str:
    lines = [
        "# 公网研究四臂匿名评分材料",
        "",
        "请对每份材料分别给出 1 至 5 分：项目相关性、事实支持程度、适配建议可用性、冲突处理质量。失败材料也需要评分，不能根据候选数量直接跳过。",
        "",
    ]
    for material in package.materials:
        metrics = material.quality_metrics
        lines.extend(
            [
                f"## {material.blind_label} / {material.brief_id}",
                "",
                f"- 运行状态：`{material.status.value}`",
                f"- 候选完成：{metrics.candidate_count}/{metrics.target_count}",
                f"- 可读来源：{metrics.readable_source_count}",
                f"- 可批准候选：{metrics.approvable_candidate_count}",
                f"- 运行级门禁问题：{metrics.run_issue_count}",
                f"- 候选级门禁失败：{metrics.gate_failed_candidate_count}",
                "",
            ]
        )
        if not material.bundle.candidates:
            lines.extend(["本次运行没有产出候选。", ""])
        for candidate in material.bundle.candidates:
            lines.extend(
                [
                    f"### {candidate.name}",
                    "",
                    candidate.summary,
                    "",
                    f"项目适配：{candidate.project_fit}",
                    "",
                    "证据结论：",
                    "",
                ]
            )
            for claim in candidate.claims:
                references = "、".join(claim.source_ids) or "无来源"
                lines.append(
                    f"- {claim.text}（{claim.support_status.value}；{references}）"
                )
            lines.append("")
        if material.bundle.sources:
            lines.extend(["### 来源", ""])
        for source in material.bundle.sources:
            lines.append(
                f"- `{source.source_id}` [{source.title or source.url}]({source.url})："
                f"{source.excerpt or source.read_status.value}"
            )
        if material.bundle.sources:
            lines.append("")
        if material.gate_report.run_issues:
            lines.extend(["### 门禁说明", ""])
            for issue in material.gate_report.run_issues:
                lines.append(f"- `{issue.code}`：{issue.message}")
            lines.append("")
    return "\n".join(lines)


def create_blind_mapping(
    policy: ExperimentPolicy,
    *,
    created_at: datetime,
    label_order: list[str] | None = None,
) -> BlindMapping:
    labels = label_order or random.SystemRandom().sample(list("ABCD"), 4)
    if sorted(labels) != list("ABCD"):
        raise ValueError("匿名标签必须恰好包含 A、B、C、D")
    return BlindMapping(
        experiment_id=policy.experiment_id,
        policy_version=policy.version,
        created_at=created_at,
        entries=[
            BlindMappingEntry(blind_label=label, arm=arm)
            for arm, label in zip(policy.arms, labels, strict=True)
        ],
    )


def build_blind_package(
    policy: ExperimentPolicy,
    mapping: BlindMapping,
    records: Iterable[EvaluationRunRecord],
    *,
    created_at: datetime,
) -> BlindPackage:
    _validate_mapping(policy, mapping)
    records_by_key = _index_records(policy, records)
    labels_by_arm = {entry.arm: entry.blind_label for entry in mapping.entries}
    materials = []
    for (arm, brief_id), record in sorted(
        records_by_key.items(),
        key=lambda item: (labels_by_arm[item[0][0]], item[0][1]),
    ):
        metrics = calculate_run_metrics(record)
        blind_bundle, blind_gate_report = _anonymize_material(record)
        materials.append(
            BlindMaterial(
                blind_label=labels_by_arm[arm],
                brief_id=brief_id,
                brief_version=record.brief.version,
                status=record.summary.status,
                bundle=blind_bundle,
                gate_report=blind_gate_report,
                quality_metrics=_blind_quality_metrics(metrics),
            )
        )
    return BlindPackage(
        experiment_id=policy.experiment_id,
        policy_version=policy.version,
        created_at=created_at,
        materials=materials,
    )


def lock_score_submission(
    package: BlindPackage,
    submission: BlindScoreSubmission,
    *,
    locked_at: datetime,
) -> LockedScoreSet:
    if (
        submission.experiment_id != package.experiment_id
        or submission.policy_version != package.policy_version
    ):
        raise ValueError("评分提交与匿名材料不属于同一实验版本")
    return lock_scores(
        package,
        [
            BlindScoreRecord(
                experiment_id=submission.experiment_id,
                brief_id=item.brief_id,
                blind_label=item.blind_label,
                scorer=submission.scorer,
                scored_at=locked_at,
                score=item.to_quality_score(),
            )
            for item in submission.records
        ],
        locked_at=locked_at,
    )


def lock_scores(
    package: BlindPackage,
    records: Iterable[BlindScoreRecord],
    *,
    locked_at: datetime,
) -> LockedScoreSet:
    score_records = list(records)
    expected_keys = {
        (material.blind_label, material.brief_id)
        for material in package.materials
    }
    actual_keys = {
        (record.blind_label, record.brief_id) for record in score_records
    }
    if actual_keys != expected_keys or len(score_records) != len(expected_keys):
        missing = sorted(expected_keys - actual_keys)
        unexpected = sorted(actual_keys - expected_keys)
        raise ValueError(
            f"评分必须完整覆盖匿名材料；缺少={missing}，越界={unexpected}"
        )
    if any(record.experiment_id != package.experiment_id for record in score_records):
        raise ValueError("评分记录与匿名材料不属于同一实验")
    return LockedScoreSet(
        experiment_id=package.experiment_id,
        policy_version=package.policy_version,
        locked_at=locked_at,
        records=score_records,
    )


def reveal_comparison(
    policy: ExperimentPolicy,
    mapping: BlindMapping,
    locked_scores: LockedScoreSet,
    records: Iterable[EvaluationRunRecord],
    *,
    generated_at: datetime,
) -> ComparisonReport:
    _validate_mapping(policy, mapping)
    if (
        locked_scores.experiment_id != policy.experiment_id
        or locked_scores.policy_version != policy.version
    ):
        raise ValueError("锁定评分与实验策略不一致")
    records_by_key = _index_records(policy, records)
    arm_by_label = {entry.blind_label: entry.arm for entry in mapping.entries}
    scores_by_key = {
        (arm_by_label[score.blind_label], score.brief_id): score.score
        for score in locked_scores.records
    }
    if set(scores_by_key) != set(records_by_key):
        raise ValueError("揭盲评分与实际运行集合不一致")

    expected_keys = _expected_run_keys(policy)
    missing_keys = sorted(
        expected_keys - records_by_key.keys(),
        key=lambda item: (item[0].value, item[1]),
    )
    results = [
        RevealedRunResult(
            arm=arm,
            brief_id=brief_id,
            metrics=calculate_run_metrics(record),
            score=scores_by_key[(arm, brief_id)],
        )
        for (arm, brief_id), record in sorted(
            records_by_key.items(),
            key=lambda item: (item[0][0].value, item[0][1]),
        )
    ]
    wins, extra_approvable, added_gate_failures = _project_multi_results(results)
    complete = not missing_keys
    if not complete:
        recommendation = RetentionRecommendation.INCONCLUSIVE
    elif (
        added_gate_failures == 0
        and wins >= policy.retention_rule.required_brief_wins
        and extra_approvable
        >= policy.retention_rule.required_extra_approvable_candidates
    ):
        recommendation = RetentionRecommendation.KEEP_MULTI_AGENT
    else:
        recommendation = RetentionRecommendation.KEEP_SINGLE_AGENT

    return ComparisonReport(
        experiment_id=policy.experiment_id,
        policy_version=policy.version,
        generated_at=generated_at,
        complete_four_arm_comparison=complete,
        missing_results=[f"{arm.value}:{brief_id}" for arm, brief_id in missing_keys],
        results=results,
        project_multi_brief_wins=wins,
        project_multi_extra_approvable_candidates=extra_approvable,
        project_multi_added_gate_failures=added_gate_failures,
        recommendation=recommendation,
        interpretation_notes=[
            "PROJECT_SINGLE 与 PROJECT_MULTI 只比较同模型、同工具下的角色拆分效果。",
            "项目执行臂与 Codex 执行臂的差异同时包含模型、搜索能力和运行环境影响。",
        ],
    )


def _blind_quality_metrics(metrics: RunEvaluationMetrics) -> BlindQualityMetrics:
    return BlindQualityMetrics(
        schema_pass_rate=metrics.schema_pass_rate,
        target_count=metrics.target_count,
        candidate_count=metrics.candidate_count,
        target_completion=metrics.target_completion,
        readable_source_count=metrics.readable_source_count,
        traceable_claim_rate=metrics.traceable_claim_rate,
        evidence_supported_candidate_count=(
            metrics.evidence_supported_candidate_count
        ),
        approvable_candidate_count=metrics.approvable_candidate_count,
        explicit_conflict_claim_rate=metrics.explicit_conflict_claim_rate,
        unsupported_claim_count=metrics.unsupported_claim_count,
        duplicate_candidate_count=metrics.duplicate_candidate_count,
        run_issue_count=metrics.run_issue_count,
        gate_failed_candidate_count=metrics.gate_failed_candidate_count,
    )


def _anonymize_material(
    record: EvaluationRunRecord,
) -> tuple[CandidateBundle, GateReport]:
    source_ids = [source.source_id for source in record.bundle.sources]
    source_ids.extend(
        source_id
        for candidate in record.bundle.candidates
        for claim in candidate.claims
        for source_id in claim.source_ids
        if source_id not in source_ids
    )
    source_id_map = {
        source_id: f"source-blind-{index:03d}"
        for index, source_id in enumerate(dict.fromkeys(source_ids), start=1)
    }
    candidate_id_map = {
        candidate.candidate_id: f"candidate-blind-{index:03d}"
        for index, candidate in enumerate(record.bundle.candidates, start=1)
    }
    excerpt_id_map = {
        excerpt_id: f"{source_id_map[source.source_id]}-excerpt-{index:03d}"
        for source in record.bundle.sources
        for index, excerpt_id in enumerate(source.excerpt_ids, start=1)
    }
    text_replacements = {
        **source_id_map,
        **candidate_id_map,
        **excerpt_id_map,
    }

    def anonymize_text(value: str | None) -> str | None:
        if value is None:
            return None
        result = value
        for original, replacement in sorted(
            text_replacements.items(),
            key=lambda item: len(item[0]),
            reverse=True,
        ):
            result = result.replace(original, replacement)
        return result

    sources = []
    for source in record.bundle.sources:
        blind_source_id = source_id_map[source.source_id]
        sources.append(
            source.model_copy(
                update={
                    "source_id": blind_source_id,
                    "excerpt_ids": [
                        excerpt_id_map[excerpt_id]
                        for excerpt_id in source.excerpt_ids
                    ],
                    "title": anonymize_text(source.title),
                    "publisher": anonymize_text(source.publisher),
                    "excerpt": anonymize_text(source.excerpt),
                    "error_category": anonymize_text(source.error_category),
                }
            )
        )
    candidates = []
    for candidate in record.bundle.candidates:
        candidates.append(
            candidate.model_copy(
                update={
                    "candidate_id": candidate_id_map[candidate.candidate_id],
                    "name": anonymize_text(candidate.name),
                    "summary": anonymize_text(candidate.summary),
                    "project_fit": anonymize_text(candidate.project_fit),
                    "claims": [
                        claim.model_copy(
                            update={
                                "text": anonymize_text(claim.text),
                                "source_ids": [
                                    source_id_map[source_id]
                                    for source_id in claim.source_ids
                                ],
                                "review_note": anonymize_text(claim.review_note),
                            }
                        )
                        for claim in candidate.claims
                    ],
                }
            )
        )
    bundle = CandidateBundle(
        brief_id=record.bundle.brief_id,
        brief_version=record.bundle.brief_version,
        sources=sources,
        candidates=candidates,
    )

    def blind_candidate_id(candidate_id: str | None) -> str | None:
        if candidate_id is None:
            return None
        return candidate_id_map.get(candidate_id, "candidate-blind-unknown")

    gate_report = record.gate_report.model_copy(
        update={
            "run_issues": [
                issue.model_copy(
                    update={
                        "message": anonymize_text(issue.message),
                        "candidate_id": blind_candidate_id(issue.candidate_id),
                    }
                )
                for issue in record.gate_report.run_issues
            ],
            "decisions": [
                decision.model_copy(
                    update={
                        "candidate_id": blind_candidate_id(decision.candidate_id),
                        "issues": [
                            issue.model_copy(
                                update={
                                    "message": anonymize_text(issue.message),
                                    "candidate_id": blind_candidate_id(
                                        issue.candidate_id
                                    )
                                }
                            )
                            for issue in decision.issues
                        ],
                    }
                )
                for decision in record.gate_report.decisions
            ],
            "approvable_candidate_ids": [
                blind_candidate_id(candidate_id)
                for candidate_id in record.gate_report.approvable_candidate_ids
            ],
            "rejected_candidate_ids": [
                blind_candidate_id(candidate_id)
                for candidate_id in record.gate_report.rejected_candidate_ids
            ],
        }
    )
    return bundle, gate_report


def _project_multi_results(
    results: list[RevealedRunResult],
) -> tuple[int, int, int]:
    by_key = {(result.arm, result.brief_id): result for result in results}
    brief_ids = {
        result.brief_id
        for result in results
        if result.arm == ExperimentArm.PROJECT_SINGLE
    }
    wins = 0
    multi_approvable = 0
    single_approvable = 0
    multi_gate_failures = 0
    for brief_id in brief_ids:
        single = by_key.get((ExperimentArm.PROJECT_SINGLE, brief_id))
        multi = by_key.get((ExperimentArm.PROJECT_MULTI, brief_id))
        if single is None or multi is None:
            continue
        wins += multi.score.total > single.score.total
        multi_approvable += multi.metrics.approvable_candidate_count
        single_approvable += single.metrics.approvable_candidate_count
        multi_failures_for_brief = (
            multi.metrics.run_issue_count + multi.metrics.gate_failed_candidate_count
        )
        single_failures_for_brief = (
            single.metrics.run_issue_count + single.metrics.gate_failed_candidate_count
        )
        multi_gate_failures += max(
            0,
            multi_failures_for_brief - single_failures_for_brief,
        )
    return (
        wins,
        multi_approvable - single_approvable,
        multi_gate_failures,
    )


def _index_records(
    policy: ExperimentPolicy,
    records: Iterable[EvaluationRunRecord],
) -> dict[tuple[ExperimentArm, str], EvaluationRunRecord]:
    expected_briefs = dict(_official_brief_identities(policy))
    indexed = {}
    for record in records:
        if record.summary.experiment_id != policy.experiment_id:
            raise ValueError("运行结果与实验策略不一致")
        expected_version = expected_briefs.get(record.brief.brief_id)
        if expected_version != record.brief.version:
            raise ValueError("运行结果不属于冻结正式简报")
        key = (record.summary.arm, record.brief.brief_id)
        if key in indexed:
            raise ValueError("同一执行臂和简报只能导入一个正式结果")
        indexed[key] = record
    return indexed


def _expected_run_keys(
    policy: ExperimentPolicy,
) -> set[tuple[ExperimentArm, str]]:
    brief_ids = [brief_id for brief_id, _ in _official_brief_identities(policy)]
    return {(arm, brief_id) for arm in policy.arms for brief_id in brief_ids}


def _official_brief_identities(
    policy: ExperimentPolicy,
) -> list[tuple[str, str]]:
    identities = []
    for filename in policy.official_brief_files:
        match = _OFFICIAL_BRIEF_FILE.fullmatch(filename)
        if match is None:
            raise ValueError(f"无法从正式简报文件名解析版本：{filename}")
        identities.append((match.group("brief_id"), match.group("version")))
    return identities


def _validate_mapping(policy: ExperimentPolicy, mapping: BlindMapping) -> None:
    if (
        mapping.experiment_id != policy.experiment_id
        or mapping.policy_version != policy.version
    ):
        raise ValueError("匿名映射与实验策略不一致")


def _sum_known(values: Iterable[int | None]) -> int | None:
    items = list(values)
    if not items or any(item is None for item in items):
        return None
    return sum(item for item in items if item is not None)


def _read_json(path: Path):
    import json

    with path.open("r", encoding="utf-8") as file:
        return json.load(file)
