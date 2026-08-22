from __future__ import annotations

import os
import threading
import unittest
import uuid

from app.config import Settings
from app.growth_memory_store import MemoryChangeType
from app.redis_growth_memory_store import RedisGrowthMemoryStore
from app.runtime import build_growth_memory_store


REDIS_URL = os.getenv(
    "GROWTH_MEMORY_REDIS_URL",
    os.getenv("EXCHANGE_CONFIRMATION_REDIS_URL", "redis://127.0.0.1:6379/0"),
)
RUN_REDIS_TESTS = os.getenv("RUN_REDIS_INTEGRATION_TESTS") == "1"


@unittest.skipUnless(
    RUN_REDIS_TESTS,
    "设置 RUN_REDIS_INTEGRATION_TESTS=1 后运行 Redis 集成测试",
)
class RedisGrowthMemoryStoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self.prefix = f"agent:test:growth-memory:{uuid.uuid4().hex}"
        self.store_a = RedisGrowthMemoryStore.from_url(
            REDIS_URL,
            key_prefix=self.prefix,
        )
        self.store_b = RedisGrowthMemoryStore.from_url(
            REDIS_URL,
            key_prefix=self.prefix,
        )

    def tearDown(self) -> None:
        self.store_b.clear()
        self.store_a.close()
        self.store_b.close()

    def prepare_goal(self):
        return self.store_a.prepare(
            user_id=10,
            session_id="user:10:session:a",
            change_type=MemoryChangeType.UPSERT_GOAL,
            payload={
                "target_award_id": 6,
                "target_award_name": "城市随行保温杯",
                "target_date": "2026-09-01",
            },
            summary="设置兑换目标",
        )

    def test_factory_and_cross_instance_read(self):
        store = build_growth_memory_store(
            Settings(
                growth_memory_store="redis",
                growth_memory_redis_url=REDIS_URL,
                growth_memory_redis_prefix=f"{self.prefix}:factory",
            )
        )
        try:
            self.assertIsInstance(store, RedisGrowthMemoryStore)
        finally:
            store.clear()
            store.close()

        self.prepare_goal()
        self.assertIsNotNone(
            self.store_b.pending_for(
                user_id=10,
                session_id="user:10:session:a",
            )
        )
        self.store_b.confirm(user_id=10, session_id="user:10:session:a")
        self.assertEqual(6, self.store_a.get(10).goal.target_award_id)

    def test_cross_instance_concurrent_confirm_has_one_winner(self):
        self.prepare_goal()
        barrier = threading.Barrier(20)
        applied: list[bool] = []
        lock = threading.Lock()

        def confirm(index: int) -> None:
            barrier.wait()
            store = self.store_a if index % 2 == 0 else self.store_b
            result = store.confirm(user_id=10, session_id="user:10:session:a")
            with lock:
                applied.append(result.applied)

        threads = [threading.Thread(target=confirm, args=(index,)) for index in range(20)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(1, applied.count(True))
        self.assertEqual(19, applied.count(False))
        self.assertEqual(6, self.store_b.get(10).goal.target_award_id)


if __name__ == "__main__":
    unittest.main()
