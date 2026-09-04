from __future__ import annotations

import json
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

from app.research.agents import SingleResearchRun
from app.research.cli import run_research
from app.research.gates import evaluate_candidate_bundle
from app.research.models import (
    CandidateBundle,
    EvidenceReviewOutput,
    ExperimentArm,
    ResearchPlan,
    RunStatus,
    RunSummary,
    load_research_brief,
)
from app.research.workflow import MultiResearchRun


BRIEF_PATH = (
    Path(__file__).resolve().parents[1]
    / "research-data"
    / "briefs"
    / "pilot-mixed-v1.json"
)


class FakeWebClient:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        del exc_type, exc_value, traceback


class ResearchCliTest(unittest.TestCase):
    def args(
        self,
        runs_root: Path,
        run_id: str,
        *,
        arm: ExperimentArm = ExperimentArm.PROJECT_SINGLE,
    ) -> Namespace:
        return Namespace(
            command="run",
            arm=arm.value,
            brief=BRIEF_PATH,
            experiment_id="experiment-pilot",
            run_id=run_id,
            runs_root=runs_root,
        )

    def test_success_writes_brief_bundle_summary_and_gate_report(self):
        brief = load_research_brief(BRIEF_PATH)
        bundle = CandidateBundle(
            brief_id=brief.brief_id,
            brief_version=brief.version,
        )
        now = "2026-09-04T06:00:00+00:00"
        summary = RunSummary.model_validate(
            {
                "experiment_id": "experiment-pilot",
                "run_id": "run-success-001",
                "brief_id": brief.brief_id,
                "brief_version": brief.version,
                "run_kind": brief.run_kind,
                "arm": "PROJECT_SINGLE",
                "status": RunStatus.COMPLETED,
                "started_at": now,
                "completed_at": now,
            }
        )
        fake_run = SingleResearchRun(bundle=bundle, summary=summary)

        with tempfile.TemporaryDirectory() as temp_dir, patch(
            "app.research.cli.PublicWebClient",
            return_value=FakeWebClient(),
        ), patch(
            "app.research.cli.build_single_research_agents",
            return_value=(object(), object()),
        ), patch(
            "app.research.cli.SingleResearchRunner.run",
            return_value=fake_run,
        ):
            result = run_research(self.args(Path(temp_dir), "run-success-001"))
            run_dir = (
                Path(temp_dir)
                / "experiment-pilot"
                / "PROJECT_SINGLE"
                / "run-success-001"
            )

            self.assertEqual(0, result)
            self.assertEqual(
                {"brief.json", "bundle.json", "summary.json", "gate-report.json"},
                {path.name for path in run_dir.iterdir()},
            )

    def test_multi_success_writes_plan_review_and_shared_outputs(self):
        brief = load_research_brief(BRIEF_PATH)
        bundle = CandidateBundle(
            brief_id=brief.brief_id,
            brief_version=brief.version,
        )
        plan = ResearchPlan.model_validate(
            {
                "brief_id": brief.brief_id,
                "brief_version": brief.version,
                "tasks": [
                    {
                        "task_id": "task-award",
                        "focus_key": "award-focus",
                        "objective": "Research one public award candidate source.",
                        "asset_types": ["AWARD_CANDIDATE"],
                        "target_count": 1,
                        "search_queries": ["official product specs"],
                        "max_pages": 2,
                    }
                ],
            }
        )
        review = EvidenceReviewOutput(
            brief_id=brief.brief_id,
            brief_version=brief.version,
        )
        now = "2026-09-04T06:00:00+00:00"
        summary = RunSummary.model_validate(
            {
                "experiment_id": "experiment-pilot",
                "run_id": "run-multi-success-001",
                "brief_id": brief.brief_id,
                "brief_version": brief.version,
                "run_kind": brief.run_kind,
                "arm": "PROJECT_MULTI",
                "status": RunStatus.COMPLETED,
                "started_at": now,
                "completed_at": now,
            }
        )
        fake_run = MultiResearchRun(
            plan=plan,
            bundle=bundle,
            gate_report=evaluate_candidate_bundle(brief, bundle),
            summary=summary,
            review=review,
        )

        with tempfile.TemporaryDirectory() as temp_dir, patch(
            "app.research.cli.build_research_planning_agent",
            return_value=object(),
        ), patch(
            "app.research.cli.build_evidence_review_agent",
            return_value=object(),
        ), patch(
            "app.research.cli.MultiResearchWorkflow.run",
            return_value=fake_run,
        ):
            result = run_research(
                self.args(
                    Path(temp_dir),
                    "run-multi-success-001",
                    arm=ExperimentArm.PROJECT_MULTI,
                )
            )
            run_dir = (
                Path(temp_dir)
                / "experiment-pilot"
                / "PROJECT_MULTI"
                / "run-multi-success-001"
            )

            self.assertEqual(0, result)
            self.assertEqual(
                {
                    "brief.json",
                    "plan.json",
                    "review.json",
                    "bundle.json",
                    "summary.json",
                    "gate-report.json",
                },
                {path.name for path in run_dir.iterdir()},
            )

    def test_failure_is_persisted_with_stage_without_secret_values(self):
        with tempfile.TemporaryDirectory() as temp_dir, patch(
            "app.research.cli.Settings.from_env",
            side_effect=ValueError("missing model configuration"),
        ):
            result = run_research(self.args(Path(temp_dir), "run-failure-001"))
            failure_path = (
                Path(temp_dir)
                / "experiment-pilot"
                / "PROJECT_SINGLE"
                / "run-failure-001"
                / "failure.json"
            )
            failure = json.loads(failure_path.read_text(encoding="utf-8"))

            self.assertEqual(1, result)
            self.assertEqual("PROJECT_SINGLE_RUN", failure["failure_stage"])
            self.assertEqual("ValueError", failure["error_category"])


if __name__ == "__main__":
    unittest.main()
