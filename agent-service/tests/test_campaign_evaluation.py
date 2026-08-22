from __future__ import annotations

import unittest

from app.models import CampaignPlanDraft
from evals.campaign_runner import evaluate_suite, load_suite, score_draft


class CampaignEvaluationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.suite = load_suite()

    def test_frozen_campaign_baseline_passes_all_four_metric_groups(self):
        report = evaluate_suite(self.suite)

        self.assertEqual(8, report["summary"]["passed_cases"])
        self.assertEqual(8, report["summary"]["total_cases"])
        self.assertEqual(
            {
                "permission_isolation",
                "data_reference_correctness",
                "constraint_satisfaction",
                "draft_completeness",
            },
            set(report["summary"]["categories"]),
        )
        for metric in report["summary"]["categories"].values():
            self.assertEqual(1.0, metric["rate"])

    def test_source_reference_tampering_is_detected(self):
        case, snapshot, draft = self._ready_case_and_draft()
        draft.suggested_tasks[0].source_ref = "untrusted:task:1"

        checks = score_draft(case, snapshot, draft)

        failed = [check for check in checks if not check["passed"]]
        self.assertEqual(1, len(failed))
        self.assertEqual("data_reference_correctness", failed[0]["category"])
        self.assertIn("任务字段和来源", failed[0]["name"])

    def test_cost_tampering_is_detected(self):
        case, snapshot, draft = self._ready_case_and_draft()
        draft.estimated_point_cost = draft.budget_points + 1

        checks = score_draft(case, snapshot, draft)

        failed = [check for check in checks if not check["passed"]]
        self.assertTrue(failed)
        self.assertTrue(
            any(
                check["category"] == "constraint_satisfaction"
                and "积分成本" in check["name"]
                for check in failed
            )
        )

    def _ready_case_and_draft(self):
        report = evaluate_suite(self.suite, {"C01"})
        case = next(item for item in self.suite["cases"] if item["id"] == "C01")
        snapshot = self.suite["snapshots"][case["snapshot"]].model_copy(deep=True)
        draft = CampaignPlanDraft.model_validate(report["results"][0]["output"])
        return case, snapshot, draft


if __name__ == "__main__":
    unittest.main()
