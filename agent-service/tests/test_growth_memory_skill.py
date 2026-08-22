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
        queried = self.skill.get(10, include_all=True)
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


    def test_generic_memory_tool_accepts_incomplete_natural_language_memory(self):
        tools = build_tools(
            AwardClient(),
            10,
            growth_memory_store=self.store,
        )
        by_name = {item.name: item for item in tools}

        with bind_execution_context("user:10:session:natural-memory"):
            result = by_name["remember_user_memory"].invoke(
                {
                    "memory_type": "goal",
                    "raw_text": "我打算明年换一个手环",
                    "subject": "手环",
                    "time_expression": "明年",
                    "target_year": 2027,
                }
            )

        self.assertEqual("MEMORY_ADDED", result["code"])
        self.assertEqual("我打算明年换一个手环", result["data"]["memory"]["rawText"])
        queried = by_name["get_growth_memory"].invoke(
            {"query": "我的手环计划", "memory_types": ["goal"], "limit": 3}
        )
        self.assertEqual(1, len(queried["data"]["memories"]))
        self.assertNotIn("sourceSession", queried["data"]["memories"][0])

    def test_query_returns_only_relevant_memory(self):
        self.skill.remember(
            user_id=10,
            session_id="user:10:session:a",
            memory_type="preference",
            raw_text="我喜欢小鸟",
            subject="小鸟",
            polarity="LIKE",
        )
        self.skill.remember(
            user_id=10,
            session_id="user:10:session:a",
            memory_type="goal",
            raw_text="我打算明年换一个手环",
            subject="手环",
            time_expression="明年",
            target_year=2027,
        )

        queried = self.skill.get(
            10,
            query="帮我看看手环计划",
            memory_types=["goal"],
            limit=3,
        )

        self.assertEqual("FILTERED", queried.data["retrieval"]["mode"])
        self.assertEqual(2, queried.data["retrieval"]["totalActive"])
        self.assertEqual(1, queried.data["retrieval"]["returned"])
        self.assertEqual("我打算明年换一个手环", queried.data["memories"][0]["rawText"])
        self.assertIsNone(queried.data["goal"])
        self.assertIsNone(queried.data["preferences"])

    def test_type_filter_handles_generic_preference_question(self):
        for subject in ["数码类商品", "小鸟"]:
            self.skill.remember(
                user_id=10,
                session_id="user:10:session:a",
                memory_type="preference",
                raw_text=f"我喜欢{subject}",
                subject=subject,
                polarity="LIKE",
            )
        self.skill.remember(
            user_id=10,
            session_id="user:10:session:a",
            memory_type="profile",
            raw_text="我是一名 Java 开发者",
            subject="职业",
        )

        queried = self.skill.get(
            10,
            query="你记得我喜欢什么吗",
            memory_types=["preference"],
            limit=5,
        )

        self.assertEqual(2, queried.data["retrieval"]["returned"])
        self.assertTrue(
            all(item["memoryType"] == "preference" for item in queried.data["memories"])
        )

    def test_unrelated_query_does_not_inject_memory_without_type_filter(self):
        self.skill.remember(
            user_id=10,
            session_id="user:10:session:a",
            memory_type="preference",
            raw_text="我喜欢小鸟",
            subject="小鸟",
            polarity="LIKE",
        )

        queried = self.skill.get(10, query="查询当前订单状态", limit=5)

        self.assertEqual("GROWTH_MEMORY_EMPTY", queried.code)
        self.assertEqual([], queried.data["memories"])

    def test_explicit_all_returns_every_memory_and_legacy_projection(self):
        self.skill.save_goal(
            user_id=10,
            session_id="user:10:session:a",
            award_id=6,
            target_date=date(2026, 9, 1),
        )
        self.skill.remember(
            user_id=10,
            session_id="user:10:session:a",
            memory_type="preference",
            raw_text="我喜欢数码类商品",
            subject="数码类商品",
            polarity="LIKE",
        )

        queried = self.skill.get(10, include_all=True, limit=1)

        self.assertEqual("ALL", queried.data["retrieval"]["mode"])
        self.assertEqual(2, queried.data["retrieval"]["returned"])
        self.assertEqual(6, queried.data["goal"]["targetAwardId"])


if __name__ == "__main__":
    unittest.main()
