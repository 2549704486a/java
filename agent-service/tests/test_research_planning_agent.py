from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from pydantic import ValidationError

from app.research.agents import ResearchPlanningRunner
from app.research.models import load_research_brief


BRIEFS_DIR = Path(__file__).resolve().parents[1] / "research-data" / "briefs"


class FakePlanningAgent:
    def __init__(self, structured_response) -> None:
        self.structured_response = structured_response

    def invoke(self, inputs, config):
        del inputs, config
        return {"messages": [], "structured_response": self.structured_response}


class ResearchPlanningAgentTest(unittest.TestCase):
    def setUp(self) -> None:
        self.brief = load_research_brief(BRIEFS_DIR / "pilot-mixed-v1.json")

    def valid_plan_payload(self) -> dict:
        return {
            "brief_id": self.brief.brief_id,
            "brief_version": self.brief.version,
            "tasks": [
                {
                    "task_id": "task-award",
                    "focus_key": "award-product-specs",
                    "objective": "研究公开商品规格及其可核验的价格口径",
                    "asset_types": ["AWARD_CANDIDATE"],
                    "search_queries": ["official smart band specifications"],
                    "max_pages": 2,
                },
                {
                    "task_id": "task-campaign",
                    "focus_key": "campaign-reward-mechanism",
                    "objective": "研究公开会员活动的积分获取和兑换机制",
                    "asset_types": ["CAMPAIGN_PATTERN"],
                    "search_queries": ["official membership rewards terms"],
                    "max_pages": 2,
                },
                {
                    "task_id": "task-segment",
                    "focus_key": "segment-computable-fields",
                    "objective": "研究可由内部事件字段计算的客群规则模板",
                    "asset_types": ["SEGMENT_RULE_TEMPLATE"],
                    "search_queries": ["official RFM segmentation documentation"],
                    "max_pages": 2,
                },
            ],
        }

    def test_valid_plan_has_no_public_web_tool_calls(self):
        with patch("app.research.web.PublicWebClient.search") as search, patch(
            "app.research.web.PublicWebClient.fetch"
        ) as fetch:
            run = ResearchPlanningRunner(
                FakePlanningAgent(self.valid_plan_payload())
            ).run(self.brief)

        self.assertEqual(3, len(run.plan.tasks))
        self.assertEqual(0, run.stage.tool_call_count)
        search.assert_not_called()
        fetch.assert_not_called()

    def test_incomplete_and_over_budget_plans_fail_before_web_access(self):
        incomplete = self.valid_plan_payload()
        incomplete["tasks"][0]["asset_types"] = ["CAMPAIGN_PATTERN"]
        over_budget = self.valid_plan_payload()
        for task in over_budget["tasks"]:
            task["max_pages"] = 3

        for payload, message in (
            (incomplete, "没有覆盖简报目标"),
            (over_budget, "页面预算总和"),
        ):
            with self.subTest(message=message), patch(
                "app.research.web.PublicWebClient.search"
            ) as search, patch("app.research.web.PublicWebClient.fetch") as fetch:
                with self.assertRaisesRegex(ValueError, message):
                    ResearchPlanningRunner(FakePlanningAgent(payload)).run(self.brief)
                search.assert_not_called()
                fetch.assert_not_called()

    def test_out_of_scope_asset_type_is_rejected(self):
        brief = load_research_brief(BRIEFS_DIR / "official-awards-v1.json")
        payload = {
            "brief_id": brief.brief_id,
            "brief_version": brief.version,
            "tasks": [
                {
                    "task_id": "task-campaign",
                    "focus_key": "campaign-mechanism",
                    "objective": "研究公开会员活动的积分获取和兑换机制",
                    "asset_types": ["CAMPAIGN_PATTERN"],
                    "search_queries": ["official membership rewards terms"],
                    "max_pages": 2,
                }
            ],
        }

        with self.assertRaisesRegex(ValueError, "范围外的资产类型"):
            ResearchPlanningRunner(FakePlanningAgent(payload)).run(brief)

    def test_duplicate_empty_and_unparseable_plans_are_rejected(self):
        duplicate = self.valid_plan_payload()
        duplicate["tasks"][1]["focus_key"] = duplicate["tasks"][0]["focus_key"]
        empty = {
            "brief_id": self.brief.brief_id,
            "brief_version": self.brief.version,
            "tasks": [],
        }

        for payload in (duplicate, empty, "not-a-structured-plan"):
            with self.subTest(payload=payload):
                with self.assertRaises(ValidationError):
                    ResearchPlanningRunner(FakePlanningAgent(payload)).run(self.brief)


if __name__ == "__main__":
    unittest.main()
