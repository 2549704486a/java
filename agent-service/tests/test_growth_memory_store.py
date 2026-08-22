from __future__ import annotations

import unittest
from datetime import date, datetime, timezone

from app.growth_memory_store import GrowthMemoryStore


class GrowthMemoryStoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self.now = [datetime(2026, 8, 22, 8, 0, tzinfo=timezone.utc)]
        self.store = GrowthMemoryStore(now_provider=lambda: self.now[0])

    def save_goal(self, user_id: int = 10, session_id: str = "user:10:session:a"):
        return self.store.save_goal(
            user_id=user_id,
            source_session=session_id,
            target_award_id=6,
            target_award_name="城市随行保温杯",
            target_date=date(2026, 9, 1),
        )

    def test_explicit_goal_write_is_immediate_and_cross_session_readable(self):
        result = self.save_goal()

        self.assertTrue(result.applied)
        self.assertEqual("REDEMPTION_GOAL_SAVED", result.code)
        goal = self.store.get(10).goal
        self.assertEqual(6, goal.target_award_id)
        self.assertEqual("user:10:session:a", goal.source_session)
        # 长期记录按用户保存，读取不依赖创建它的旧会话。
        self.assertEqual(6, self.store.get(10).goal.target_award_id)

    def test_users_are_isolated(self):
        self.save_goal(user_id=10)

        self.assertIsNone(self.store.get(11).goal)

    def test_goal_status_changes_to_expired_and_forget_is_immediate(self):
        self.save_goal()
        self.now[0] = datetime(2026, 9, 2, 8, 0, tzinfo=timezone.utc)

        self.assertEqual("EXPIRED", self.store.get(10).goal.status)
        result = self.store.forget(user_id=10, scope="goal")

        self.assertTrue(result.applied)
        self.assertEqual("GROWTH_MEMORY_FORGOTTEN", result.code)
        self.assertIsNone(self.store.get(10).goal)

    def test_preferences_replace_existing_value_and_preserve_created_time(self):
        first = self.store.replace_preferences(
            user_id=10,
            source_session="user:10:session:a",
            preferred_categories=["实物"],
            disliked_categories=[],
            task_preferences=["签到"],
        )
        created_at = first.memory.preferences.created_at
        self.now[0] = datetime(2026, 8, 23, 8, 0, tzinfo=timezone.utc)

        second = self.store.replace_preferences(
            user_id=10,
            source_session="user:10:session:b",
            preferred_categories=["优惠券"],
            disliked_categories=["虚拟装扮"],
            task_preferences=[],
        )

        self.assertEqual(created_at, second.memory.preferences.created_at)
        self.assertEqual(["优惠券"], second.memory.preferences.preferred_categories)
        self.assertEqual("user:10:session:b", second.memory.preferences.source_session)


if __name__ == "__main__":
    unittest.main()
