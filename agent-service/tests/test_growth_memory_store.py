from __future__ import annotations

import threading
import unittest
from datetime import datetime, timedelta, timezone

from app.growth_memory_store import GrowthMemoryStore, MemoryChangeType


class GrowthMemoryStoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self.now = [datetime(2026, 8, 22, 8, 0, tzinfo=timezone.utc)]
        self.store = GrowthMemoryStore(
            pending_ttl_seconds=120,
            now_provider=lambda: self.now[0],
        )

    def prepare_goal(self, session_id: str = "user:10:session:a"):
        return self.store.prepare(
            user_id=10,
            session_id=session_id,
            change_type=MemoryChangeType.UPSERT_GOAL,
            payload={
                "target_award_id": 6,
                "target_award_name": "城市随行保温杯",
                "target_date": "2026-09-01",
            },
            summary="设置兑换目标",
        )

    def test_draft_is_not_visible_until_confirmed_and_then_cross_session_readable(self):
        self.prepare_goal()

        self.assertIsNone(self.store.get(10).goal)
        result = self.store.confirm(user_id=10, session_id="user:10:session:a")

        self.assertTrue(result.applied)
        goal = self.store.get(10).goal
        self.assertEqual(6, goal.target_award_id)
        self.assertEqual("user:10:session:a", goal.source_session)
        self.assertIsNone(
            self.store.pending_for(user_id=10, session_id="user:10:session:a")
        )
        # 长期记录按用户保存，读取不依赖创建它的旧会话。
        self.assertEqual(6, self.store.get(10).goal.target_award_id)

    def test_user_and_session_are_isolated(self):
        self.prepare_goal()

        self.assertIsNone(
            self.store.pending_for(user_id=11, session_id="user:10:session:a")
        )
        denied = self.store.confirm(user_id=11, session_id="user:10:session:a")

        self.assertFalse(denied.applied)
        self.assertIsNotNone(
            self.store.pending_for(user_id=10, session_id="user:10:session:a")
        )

    def test_pending_change_expires_without_writing(self):
        self.prepare_goal()
        self.now[0] += timedelta(seconds=121)

        result = self.store.confirm(user_id=10, session_id="user:10:session:a")

        self.assertFalse(result.applied)
        self.assertEqual("MEMORY_CHANGE_EXPIRED", result.code)
        self.assertIsNone(self.store.get(10).goal)

    def test_goal_status_changes_to_expired_and_forget_requires_confirmation(self):
        self.prepare_goal()
        self.store.confirm(user_id=10, session_id="user:10:session:a")
        self.now[0] = datetime(2026, 9, 2, 8, 0, tzinfo=timezone.utc)

        self.assertEqual("EXPIRED", self.store.get(10).goal.status)
        self.store.prepare(
            user_id=10,
            session_id="user:10:session:b",
            change_type=MemoryChangeType.FORGET_GOAL,
            payload={},
            summary="删除兑换目标",
        )
        self.assertIsNotNone(self.store.get(10).goal)
        self.store.confirm(user_id=10, session_id="user:10:session:b")
        self.assertIsNone(self.store.get(10).goal)

    def test_concurrent_confirmation_applies_once(self):
        self.prepare_goal()
        barrier = threading.Barrier(12)
        applied: list[bool] = []
        lock = threading.Lock()

        def confirm() -> None:
            barrier.wait()
            result = self.store.confirm(
                user_id=10,
                session_id="user:10:session:a",
            )
            with lock:
                applied.append(result.applied)

        threads = [threading.Thread(target=confirm) for _ in range(12)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(1, applied.count(True))
        self.assertEqual(11, applied.count(False))


if __name__ == "__main__":
    unittest.main()
