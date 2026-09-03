from __future__ import annotations

import unittest

from app.tools import build_tools
from app.trace import capture_tool_trace, execute_traced
from evals.fixtures import FixtureBusinessApiClient


class ToolTraceTest(unittest.TestCase):
    def test_records_result_summary_without_full_business_data(self):
        with capture_tool_trace("request-001") as session:
            result = execute_traced(
                "get_user_points",
                {},
                lambda: {
                    "success": True,
                    "code": "POINTS_FOUND",
                    "data": {"userId": 10, "points": 1680},
                },
            )

        self.assertEqual(1680, result["data"]["points"])
        self.assertEqual(
            {
                "sequence": 1,
                "tool_name": "get_user_points",
                "arguments": {},
                "completed": True,
                "business_success": True,
                "result_code": "POINTS_FOUND",
                "error_type": None,
            },
            {key: value for key, value in session.as_dicts()[0].items() if key != "elapsed_ms"},
        )
        self.assertNotIn("data", session.as_dicts()[0])
        self.assertEqual(
            {"userId": 10, "points": 1680},
            session.result_evidence()[0].result["data"],
        )

    def test_records_exception_and_reraises_it(self):
        def fail():
            raise RuntimeError("内部异常")

        with capture_tool_trace("request-002") as session:
            with self.assertRaisesRegex(RuntimeError, "内部异常"):
                execute_traced("broken_tool", {"award_id": 6}, fail)

        event = session.as_dicts()[0]
        self.assertFalse(event["completed"])
        self.assertEqual("RuntimeError", event["error_type"])
        self.assertIsNone(event["result_code"])

    def test_build_tools_records_actual_skill_execution(self):
        tools = build_tools(FixtureBusinessApiClient("insufficient_cover"), 10)
        planner = next(tool for tool in tools if tool.name == "plan_points_for_award")

        with capture_tool_trace("request-003") as session:
            result = planner.invoke({"award_id": 6, "excluded_task_ids": []})

        event = session.as_dicts()[0]
        self.assertEqual("PLAN_READY", result["status"])
        self.assertEqual("plan_points_for_award", event["tool_name"])
        self.assertEqual("rest", event["transport"])
        self.assertEqual("PLAN_READY", event["result_code"])
        self.assertEqual(
            {
                "award_id": 6,
                "excluded_task_ids": [],
                "excluded_task_names": [],
                "allowed_task_names": [],
            },
            event["arguments"],
        )

    def test_local_award_detail_trace_identifies_rest_transport(self):
        tools = build_tools(FixtureBusinessApiClient("eligible"), 10)
        award_tool = next(tool for tool in tools if tool.name == "get_award_detail")

        with capture_tool_trace("request-rest") as session:
            award_tool.invoke({"award_id": 6})

        self.assertEqual("rest", session.as_dicts()[0]["transport"])

    def test_direct_business_query_identifies_rest_transport(self):
        tools = build_tools(FixtureBusinessApiClient("eligible"), 10)
        points_tool = next(tool for tool in tools if tool.name == "get_user_points")

        with capture_tool_trace("request-points-rest") as session:
            points_tool.invoke({})

        self.assertEqual("rest", session.as_dicts()[0]["transport"])


if __name__ == "__main__":
    unittest.main()
