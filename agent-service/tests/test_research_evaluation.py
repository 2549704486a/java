from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from pydantic import ValidationError

from app.research.artifacts import ResearchRunStore
from app.research.evaluation import (
    build_blind_package,
    build_evaluation_manifest,
    calculate_run_metrics,
    create_blind_mapping,
    import_external_run,
    load_evaluation_run,
    lock_scores,
    persist_blind_evaluation,
    persist_locked_scores,
    reveal_comparison,
)
from app.research.gates import evaluate_candidate_bundle
from app.research.models import (
    BlindScoreRecord,
    CandidateAsset,
    CandidateBundle,
    EvaluationRunRecord,
    EvidenceClaim,
    ExperimentArm,
    ExternalRunPayload,
    QualityScore,
    RetentionRecommendation,
    RunStatus,
    RunSummary,
    SourceDiscoveryMethod,
    SourceEvidence,
    SourceReadStatus,
    StageObservation,
    StageStatus,
    SupportStatus,
    load_experiment_policy,
    load_research_brief,
)


ROOT = Path(__file__).resolve().parents[1]
BRIEFS = ROOT / "research-data" / "briefs"
POLICY_PATH = ROOT / "research-data" / "experiment-policy-v1.json"
NOW = datetime(2026, 9, 4, 10, 0, tzinfo=timezone.utc)


class ResearchEvaluationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = load_experiment_policy(POLICY_PATH)
        self.briefs = [
            load_research_brief(BRIEFS / filename)
            for filename in self.policy.official_brief_files
        ]
        self.mapping = create_blind_mapping(
            self.policy,
            created_at=NOW,
            label_order=["D", "B", "A", "C"],
        )

    def make_record(
        self,
        brief,
        arm: ExperimentArm,
        *,
        candidate_count: int = 1,
        known_tokens: bool = True,
        identity_tag: str = "fixed",
    ) -> EvaluationRunRecord:
        source = SourceEvidence(
            source_id=f"source-{identity_tag}-page-001",
            url="https://example.com/official",
            title="Official source",
            publisher="example.com",
            retrieved_at=NOW,
            discovered_by=SourceDiscoveryMethod.BRIEF_URL,
            excerpt="This official source supports the fixed comparison candidate.",
            excerpt_ids=[f"source-{identity_tag}-page-001-excerpt-001"],
            read_status=SourceReadStatus.READABLE,
        )
        asset_type = brief.targets[0].asset_type
        candidates = [
            CandidateAsset(
                candidate_id=(
                    f"candidate-{identity_tag}-{brief.brief_id}-{index + 1:02d}"
                ),
                brief_id=brief.brief_id,
                brief_version=brief.version,
                asset_type=asset_type,
                name=f"公开候选 {index + 1}",
                summary="公开来源支持该候选的基础事实信息。",
                project_fit="可用于项目资料候选，业务参数仍需人工确认。",
                claims=[
                    EvidenceClaim(
                        text="公开来源支持这条候选事实。",
                        source_ids=[source.source_id],
                        support_status=SupportStatus.SUPPORTED,
                        review_note="固定测试证据直接支持。",
                    )
                ],
            )
            for index in range(candidate_count)
        ]
        bundle = CandidateBundle(
            brief_id=brief.brief_id,
            brief_version=brief.version,
            sources=[source],
            candidates=candidates,
        )
        stage = StageObservation(
            stage="fixed-run",
            status=StageStatus.COMPLETED,
            started_at=NOW,
            completed_at=NOW,
            model_call_count=1 if known_tokens else None,
            tool_call_count=1,
            input_tokens=100 if known_tokens else None,
            output_tokens=20 if known_tokens else None,
            output_candidate_ids=[item.candidate_id for item in candidates],
        )
        summary = RunSummary(
            experiment_id=self.policy.experiment_id,
            run_id=f"official-{brief.brief_id}-{arm.value.lower().replace('_', '-')}",
            brief_id=brief.brief_id,
            brief_version=brief.version,
            run_kind=brief.run_kind,
            arm=arm,
            status=RunStatus.COMPLETED,
            started_at=NOW,
            completed_at=NOW,
            stages=[stage],
        )
        return EvaluationRunRecord(
            brief=brief,
            bundle=bundle,
            summary=summary,
            gate_report=evaluate_candidate_bundle(brief, bundle),
        )

    def score_records(self, package, *, multi_high: bool = False):
        arm_by_label = {
            entry.blind_label: entry.arm for entry in self.mapping.entries
        }
        records = []
        for material in package.materials:
            value = (
                5
                if multi_high
                and arm_by_label[material.blind_label]
                == ExperimentArm.PROJECT_MULTI
                else 3
            )
            records.append(
                BlindScoreRecord(
                    experiment_id=self.policy.experiment_id,
                    brief_id=material.brief_id,
                    blind_label=material.blind_label,
                    scorer="fixed-reviewer",
                    scored_at=NOW,
                    score=QualityScore(
                        project_relevance=value,
                        factual_support=value,
                        adaptation_usability=value,
                        conflict_handling=value,
                        notes="固定评分用于验证揭盲和保留规则。",
                    ),
                )
            )
        return records

    def test_external_import_writes_normalized_gate_and_rejects_project_arm(self):
        record = self.make_record(self.briefs[0], ExperimentArm.CODEX_DIRECT)
        payload = ExternalRunPayload(
            brief=record.brief,
            bundle=record.bundle,
            summary=record.summary,
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            imported = import_external_run(
                payload,
                ResearchRunStore(temp_dir),
                record.brief,
            )
            run_dir = (
                Path(temp_dir)
                / self.policy.experiment_id
                / ExperimentArm.CODEX_DIRECT.value
                / record.summary.run_id
            )
            self.assertEqual(record.gate_report, imported.gate_report)
            self.assertEqual(
                {"brief.json", "bundle.json", "summary.json", "gate-report.json"},
                {path.name for path in run_dir.iterdir()},
            )

        project_record = self.make_record(
            self.briefs[0], ExperimentArm.PROJECT_SINGLE
        )
        with tempfile.TemporaryDirectory() as temp_dir, self.assertRaisesRegex(
            ValueError, "Codex"
        ):
            import_external_run(
                ExternalRunPayload(
                    brief=project_record.brief,
                    bundle=project_record.bundle,
                    summary=project_record.summary,
                ),
                ResearchRunStore(temp_dir),
                project_record.brief,
            )

    def test_external_import_rejects_modified_copy_of_frozen_brief(self):
        record = self.make_record(self.briefs[0], ExperimentArm.CODEX_DIRECT)
        modified_brief = record.brief.model_copy(
            update={"title": "被外部执行臂修改的简报"}
        )

        with tempfile.TemporaryDirectory() as temp_dir, self.assertRaisesRegex(
            ValueError, "冻结正式简报"
        ):
            import_external_run(
                ExternalRunPayload(
                    brief=modified_brief,
                    bundle=record.bundle,
                    summary=record.summary,
                ),
                ResearchRunStore(temp_dir),
                record.brief,
            )

    def test_unknown_token_usage_remains_unknown(self):
        record = self.make_record(
            self.briefs[0],
            ExperimentArm.CODEX_DIRECT,
            known_tokens=False,
        )

        metrics = calculate_run_metrics(record)

        self.assertIsNone(metrics.input_tokens)
        self.assertIsNone(metrics.output_tokens)
        self.assertIsNone(metrics.model_call_count)
        self.assertIsNone(metrics.elapsed_seconds)
        self.assertEqual(1.0, metrics.traceable_claim_rate)

    def test_failure_only_run_is_loaded_as_zero_candidate_failed_record(self):
        brief = self.briefs[0]
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir) / "failed-run"
            run_dir.mkdir()
            (run_dir / "brief.json").write_text(
                brief.model_dump_json(indent=2),
                encoding="utf-8",
            )
            (run_dir / "failure.json").write_text(
                json.dumps(
                    {
                        "experiment_id": self.policy.experiment_id,
                        "run_id": "official-awards-project-multi-failed",
                        "brief_id": brief.brief_id,
                        "brief_version": brief.version,
                        "arm": ExperimentArm.PROJECT_MULTI.value,
                        "status": "FAILED",
                        "failure_stage": "PROJECT_MULTI_RUN",
                        "error_category": "ValueError",
                        "message": "研究计划超过冻结预算",
                        "started_at": NOW.isoformat(),
                        "completed_at": NOW.isoformat(),
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            record = load_evaluation_run(run_dir)
            metrics = calculate_run_metrics(record)

        self.assertEqual(RunStatus.FAILED, record.summary.status)
        self.assertEqual([], record.bundle.candidates)
        self.assertEqual(0.0, metrics.target_completion)
        self.assertIsNone(metrics.model_call_count)
        self.assertIsNone(metrics.tool_call_count)
        self.assertIsNone(metrics.input_tokens)
        self.assertEqual(2, metrics.run_issue_count)

    def test_blind_package_does_not_expose_arm_or_run_identity(self):
        records = [
            self.make_record(
                self.briefs[0],
                arm,
                identity_tag=arm.value.lower().replace("_", "-"),
            )
            for arm in ExperimentArm
        ]
        package = build_blind_package(
            self.policy,
            self.mapping,
            records,
            created_at=NOW,
        )
        serialized = package.model_dump_json()

        for arm in ExperimentArm:
            self.assertNotIn(arm.value, serialized)
        for record in records:
            self.assertNotIn(record.summary.run_id, serialized)
            for source in record.bundle.sources:
                self.assertNotIn(source.source_id, serialized)
            for candidate in record.bundle.candidates:
                self.assertNotIn(candidate.candidate_id, serialized)
        self.assertEqual(4, len(package.materials))
        self.assertIn("source-blind-001", serialized)
        self.assertIn("candidate-blind-001", serialized)

        payload = package.model_dump(mode="python")
        payload["materials"][0]["quality_metrics"]["arm"] = "PROJECT_SINGLE"
        with self.assertRaises(ValidationError):
            package.__class__.model_validate(payload)

    def test_score_lock_requires_every_anonymous_material_once(self):
        records = [
            self.make_record(brief, arm)
            for brief in self.briefs
            for arm in ExperimentArm
        ]
        manifest = build_evaluation_manifest(
            self.policy,
            records,
            created_at=NOW,
        )
        package = build_blind_package(
            self.policy,
            self.mapping,
            records,
            created_at=NOW,
        )
        scores = self.score_records(package)

        with self.assertRaisesRegex(ValueError, "完整覆盖"):
            lock_scores(package, scores[:-1], locked_at=NOW)

        locked = lock_scores(package, scores, locked_at=NOW)
        self.assertEqual(12, len(locked.records))

        with tempfile.TemporaryDirectory() as temp_dir:
            store = ResearchRunStore(temp_dir)
            evaluation_dir = persist_blind_evaluation(
                store,
                self.policy,
                "evaluation-fixed-001",
                manifest,
                self.mapping,
                package,
            )
            self.assertEqual(
                {
                    "blind-mapping.json",
                    "blind-package.json",
                    "blind-review.md",
                    "evaluation-input.json",
                    "score-sheet-template.json",
                },
                {path.name for path in evaluation_dir.iterdir()},
            )
            persist_locked_scores(store, evaluation_dir, locked)
            with self.assertRaises(FileExistsError):
                persist_locked_scores(store, evaluation_dir, locked)

    def test_missing_official_results_force_inconclusive_report(self):
        records = [
            self.make_record(self.briefs[0], arm) for arm in ExperimentArm
        ]
        package = build_blind_package(
            self.policy,
            self.mapping,
            records,
            created_at=NOW,
        )
        locked = lock_scores(
            package,
            self.score_records(package),
            locked_at=NOW,
        )

        report = reveal_comparison(
            self.policy,
            self.mapping,
            locked,
            records,
            generated_at=NOW,
        )

        self.assertFalse(report.complete_four_arm_comparison)
        self.assertEqual(RetentionRecommendation.INCONCLUSIVE, report.recommendation)
        self.assertEqual(8, len(report.missing_results))

    def test_predeclared_rule_can_recommend_multi_only_with_complete_results(self):
        records = []
        for brief in self.briefs:
            for arm in ExperimentArm:
                records.append(
                    self.make_record(
                        brief,
                        arm,
                        candidate_count=(
                            2 if arm == ExperimentArm.PROJECT_MULTI else 1
                        ),
                    )
                )
        package = build_blind_package(
            self.policy,
            self.mapping,
            records,
            created_at=NOW,
        )
        locked = lock_scores(
            package,
            self.score_records(package, multi_high=True),
            locked_at=NOW,
        )

        report = reveal_comparison(
            self.policy,
            self.mapping,
            locked,
            records,
            generated_at=NOW,
        )

        self.assertTrue(report.complete_four_arm_comparison)
        self.assertEqual(3, report.project_multi_brief_wins)
        self.assertEqual(3, report.project_multi_extra_approvable_candidates)
        self.assertEqual(0, report.project_multi_added_gate_failures)
        self.assertEqual(
            RetentionRecommendation.KEEP_MULTI_AGENT,
            report.recommendation,
        )


if __name__ == "__main__":
    unittest.main()
