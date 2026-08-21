from __future__ import annotations

import unittest

from evals.runner import (
    evaluate_case,
    load_cases,
    redact_blind_result,
    summarize,
)


class EvalRunnerTest(unittest.TestCase):
    def test_passes_when_tool_args_backend_and_content_match(self):
        case = {
            "required_tools": ["plan_points_for_award"],
            "allowed_tools": ["plan_points_for_award"],
            "expected_args": {
                "plan_points_for_award": {
                    "award_id": 6,
                    "excluded_task_ids": [3],
                }
            },
            "required_backend_calls": ["check_exchange_eligibility"],
            "required_groups": [["还差", "缺口"]],
            "required_facts": ["150"],
        }

        evaluation = evaluate_case(
            case,
            "当前积分缺口为 150。",
            [
                {
                    "name": "plan_points_for_award",
                    "args": {"award_id": 6, "excluded_task_ids": [3]},
                }
            ],
            [{"method": "check_exchange_eligibility", "arguments": {}}],
        )

        self.assertTrue(evaluation["passed"])

    def test_fails_on_unexpected_tool_and_wrong_arguments(self):
        case = {
            "required_tools": ["check_exchange_eligibility"],
            "allowed_tools": ["check_exchange_eligibility"],
            "expected_args": {"check_exchange_eligibility": {"award_id": 6}},
        }

        evaluation = evaluate_case(
            case,
            "可以兑换。",
            [
                {"name": "check_exchange_eligibility", "args": {"award_id": 7}},
                {"name": "get_user_points", "args": {}},
            ],
            [],
        )

        self.assertFalse(evaluation["passed"])
        self.assertFalse(evaluation["checks"]["tool_selection"])
        self.assertFalse(evaluation["checks"]["arguments"])

    def test_fails_when_selected_tool_did_not_complete(self):
        case = {
            "required_tools": ["get_user_points"],
            "allowed_tools": ["get_user_points"],
        }
        execution_trace = [
            {
                "tool_name": "get_user_points",
                "completed": False,
                "error_type": "RuntimeError",
            }
        ]

        evaluation = evaluate_case(
            case,
            "查询失败。",
            [{"name": "get_user_points", "args": {}}],
            [],
            execution_trace,
        )

        self.assertFalse(evaluation["passed"])
        self.assertFalse(evaluation["checks"]["tool_execution"])
        self.assertEqual(
            ["get_user_points"],
            evaluation["details"]["tool_execution_failures"],
        )

    def test_tuning_and_blind_cases_are_physically_separated(self):
        tuning_ids = {case["id"] for case in load_cases("fixture", None, "tuning")}
        blind_ids = {case["id"] for case in load_cases("fixture", None, "blind")}

        self.assertTrue(tuning_ids)
        self.assertTrue(blind_ids)
        self.assertTrue(tuning_ids.isdisjoint(blind_ids))

    def test_repeated_results_report_flaky_case_and_latency_variation(self):
        results = [
            self._result("B01", 1, True, 10),
            self._result("B01", 2, False, 20),
            self._result("B01", 3, True, 30),
            self._result("B02", 1, True, 15),
            self._result("B02", 2, True, 15),
            self._result("B02", 3, True, 15),
        ]

        summary = summarize(results)
        stability = summary["stability"]

        self.assertEqual(1, stability["flaky_cases"])
        self.assertEqual(1, stability["stable_passed_cases"])
        self.assertEqual("flaky", stability["cases"]["B01"]["status"])
        self.assertEqual(0.6667, stability["cases"]["B01"]["pass_rate"])
        self.assertEqual(30, stability["cases"]["B01"]["p95_elapsed_ms"])
        self.assertGreater(stability["cases"]["B01"]["elapsed_stddev_ms"], 0)

    def test_single_run_is_not_misreported_as_stable(self):
        stability = summarize([self._result("B01", 1, True, 10)])["stability"]

        self.assertEqual("single_pass", stability["cases"]["B01"]["status"])
        self.assertEqual(1, stability["single_passed_cases"])
        self.assertEqual(0, stability["stable_passed_cases"])

    def test_run_latency_is_not_overwritten_by_last_tool_latency(self):
        first = self._result("B01", 1, True, 100)
        second = self._result("B02", 1, True, 200)
        first["tool_execution_trace"] = [
            {
                "tool_name": "get_user_points",
                "elapsed_ms": 5,
                "completed": True,
            }
        ]

        summary = summarize([first, second])

        self.assertEqual(150, summary["average_elapsed_ms"])
        self.assertEqual(200, summary["p95_elapsed_ms"])
        self.assertEqual(
            5,
            summary["tool_metrics"]["get_user_points"]["average_elapsed_ms"],
        )

    def test_blind_result_redaction_removes_prompt_answer_and_trace(self):
        result = self._result("B01", 1, True, 10)
        result.update(
            {
                "question": "隐藏问题",
                "response": "隐藏回答",
                "trace": [{"content": "隐藏轨迹"}],
                "tool_calls": [{"name": "get_user_points", "args": {}}],
            }
        )

        redacted = redact_blind_result(result)

        self.assertNotIn("question", redacted)
        self.assertNotIn("response", redacted)
        self.assertNotIn("trace", redacted)
        self.assertNotIn("tool_calls", redacted)
        self.assertEqual({"tool_selection": True}, redacted["evaluation"]["checks"])

    @staticmethod
    def _result(
        case_id: str,
        attempt: int,
        passed: bool,
        elapsed_ms: float,
    ) -> dict:
        return {
            "id": case_id,
            "attempt": attempt,
            "category": "测试分类",
            "source": "fixture",
            "elapsed_ms": elapsed_ms,
            "usage": {},
            "tool_execution_trace": [],
            "evaluation": {
                "passed": passed,
                "checks": {"tool_selection": passed},
                "details": {},
            },
        }


if __name__ == "__main__":
    unittest.main()
