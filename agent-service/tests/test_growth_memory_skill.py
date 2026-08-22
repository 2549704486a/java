from __future__ import annotations

import unittest
from datetime import date

from app.growth_memory_store import GrowthMemoryStore
from app.execution_context import bind_execution_context
from app.models import ToolEnvelope
from app.skills.growth_memory import GrowthMemorySkill, explicit_memory_action
from app.tools import build_tools


class AwardClient:
    def get_award_detail(self, award_id: int) -> ToolEnvelope:
        return ToolEnvelope(
            success=True,
            code="AWARD_FOUND",
            data={
                "awardId": award_id,
                "name": "城市随行保温杯",
                "requiredPoints": 500,
                "inventory": 60,
                "endTime": "2026-09-30T23:59:59+08:00",
            },
            message="查询成功",
        )


class GrowthMemorySkillTest(unittest.TestCase):
    def setUp(self) -> None:
        self.store = GrowthMemoryStore()
        self.skill = GrowthMemorySkill(
            AwardClient(),
            self.store,
            today_provider=lambda: date(2026, 8, 22),
        )

    def test_goal_prepare_confirm_and_read(self):
        prepared = self.skill.prepare_goal(
            user_id=10,
            session_id="user:10:session:a",
            award_id=6,
            target_date=date(2026, 9, 1),
        )

        self.assertEqual("MEMORY_CONFIRMATION_REQUIRED", prepared.code)
        self.assertIsNone(self.store.get(10).goal)
        confirmed = self.skill.confirm(user_id=10, session_id="user:10:session:a")
        self.assertTrue(confirmed.applied)
        queried = self.skill.get(10)
        self.assertEqual(6, queried.data["goal"]["targetAwardId"])
        self.assertNotIn("sourceSession", queried.data["goal"])

    def test_rejects_past_or_after_activity_goal_date(self):
        past = self.skill.prepare_goal(
            user_id=10,
            session_id="user:10:session:a",
            award_id=6,
            target_date=date(2026, 8, 21),
        )
        too_late = self.skill.prepare_goal(
            user_id=10,
            session_id="user:10:session:a",
            award_id=6,
            target_date=date(2026, 10, 1),
        )

        self.assertEqual("GOAL_DATE_IN_PAST", past.code)
        self.assertEqual("GOAL_AFTER_AWARD_END", too_late.code)

    def test_preferences_are_normalized_and_conflicts_rejected(self):
        conflict = self.skill.prepare_preferences(
            user_id=10,
            session_id="user:10:session:a",
            preferred_categories=["实物"],
            disliked_categories=["实物"],
            task_preferences=[],
        )
        self.assertEqual("CONFLICTING_PREFERENCES", conflict.code)

        prepared = self.skill.prepare_preferences(
            user_id=10,
            session_id="user:10:session:a",
            preferred_categories=[" 实物 ", "实物"],
            disliked_categories=["优惠券"],
            task_preferences=["签到"],
        )
        self.assertTrue(prepared.success)
        self.skill.confirm(user_id=10, session_id="user:10:session:a")
        preferences = self.store.get(10).preferences
        self.assertEqual(["实物"], preferences.preferred_categories)

    def test_confirmation_phrases_are_conservative_and_separate_from_exchange(self):
        self.assertEqual("CONFIRM", explicit_memory_action("确认保存！"))
        self.assertEqual("CANCEL", explicit_memory_action("取消遗忘"))
        self.assertIsNone(explicit_memory_action("确认兑换"))
        self.assertIsNone(explicit_memory_action("好的"))

    def test_langchain_tools_prepare_and_query_memory_without_direct_write(self):
        tools = build_tools(
            AwardClient(),
            10,
            growth_memory_store=self.store,
        )
        by_name = {item.name: item for item in tools}
        self.assertNotIn("confirm_growth_memory", by_name)

        with bind_execution_context("user:10:session:tool-a"):
            prepared = by_name["prepare_redemption_goal"].invoke(
                {"award_id": 6, "target_date": "2026-09-01"}
            )

        self.assertEqual("MEMORY_CONFIRMATION_REQUIRED", prepared["code"])
        self.assertIsNone(self.store.get(10).goal)
        self.store.confirm(user_id=10, session_id="user:10:session:tool-a")
        queried = by_name["get_growth_memory"].invoke({})
        self.assertEqual(6, queried["data"]["goal"]["targetAwardId"])


if __name__ == "__main__":
    unittest.main()
