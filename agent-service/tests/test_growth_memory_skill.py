from __future__ import annotations

import unittest
from datetime import date

from app.execution_context import bind_execution_context
from app.growth_memory_store import GrowthMemoryStore
from app.models import ToolEnvelope
from app.skills.growth_memory import GrowthMemorySkill
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

    def test_goal_is_saved_immediately_and_readable(self):
        saved = self.skill.save_goal(
            user_id=10,
            session_id="user:10:session:a",
            award_id=6,
            target_date=date(2026, 9, 1),
        )

        self.assertEqual("REDEMPTION_GOAL_SAVED", saved.code)
        queried = self.skill.get(10)
        self.assertEqual(6, queried.data["goal"]["targetAwardId"])
        self.assertNotIn("sourceSession", queried.data["goal"])

    def test_rejects_past_or_after_activity_goal_date(self):
        past = self.skill.save_goal(
            user_id=10,
            session_id="user:10:session:a",
            award_id=6,
            target_date=date(2026, 8, 21),
        )
        too_late = self.skill.save_goal(
            user_id=10,
            session_id="user:10:session:a",
            award_id=6,
            target_date=date(2026, 10, 1),
        )

        self.assertEqual("GOAL_DATE_IN_PAST", past.code)
        self.assertEqual("GOAL_AFTER_AWARD_END", too_late.code)
        self.assertIsNone(self.store.get(10).goal)

    def test_preferences_are_saved_immediately_and_conflicts_rejected(self):
        conflict = self.skill.save_preferences(
            user_id=10,
            session_id="user:10:session:a",
            preferred_categories=["实物"],
            disliked_categories=["实物"],
            task_preferences=[],
        )
        self.assertEqual("CONFLICTING_PREFERENCES", conflict.code)

        saved = self.skill.save_preferences(
            user_id=10,
            session_id="user:10:session:a",
            preferred_categories=[" 实物 ", "实物"],
            disliked_categories=["优惠券"],
            task_preferences=["签到"],
        )

        self.assertEqual("USER_PREFERENCES_SAVED", saved.code)
        preferences = self.store.get(10).preferences
        self.assertEqual(["实物"], preferences.preferred_categories)

    def test_forget_executes_immediately_and_is_idempotent(self):
        self.skill.save_goal(
            user_id=10,
            session_id="user:10:session:a",
            award_id=6,
            target_date=date(2026, 9, 1),
        )

        forgotten = self.skill.forget(user_id=10, scope="goal")
        repeated = self.skill.forget(user_id=10, scope="goal")

        self.assertEqual("GROWTH_MEMORY_FORGOTTEN", forgotten.code)
        self.assertEqual("NOTHING_TO_FORGET", repeated.code)
        self.assertTrue(repeated.success)

    def test_langchain_tools_write_query_and_forget_without_confirmation_tool(self):
        tools = build_tools(
            AwardClient(),
            10,
            growth_memory_store=self.store,
        )
        by_name = {item.name: item for item in tools}
        self.assertNotIn("confirm_growth_memory", by_name)
        self.assertNotIn("prepare_redemption_goal", by_name)

        with bind_execution_context("user:10:session:tool-a"):
            saved = by_name["save_redemption_goal"].invoke(
                {"award_id": 6, "target_date": "2026-09-01"}
            )
            forgotten = by_name["forget_growth_memory"].invoke({"scope": "goal"})

        self.assertEqual("REDEMPTION_GOAL_SAVED", saved["code"])
        self.assertEqual("GROWTH_MEMORY_FORGOTTEN", forgotten["code"])
        queried = by_name["get_growth_memory"].invoke({})
        self.assertIsNone(queried["data"]["goal"])


if __name__ == "__main__":
    unittest.main()
