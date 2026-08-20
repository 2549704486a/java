from __future__ import annotations

import unittest

from evals.runner import evaluate_case


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


if __name__ == "__main__":
    unittest.main()
