from __future__ import annotations

import os
import unittest
import uuid
from datetime import date

from app.config import Settings
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

    def save_goal(self):
        return self.store_a.save_goal(
            user_id=10,
            source_session="user:10:session:a",
            target_award_id=6,
            target_award_name="城市随行保温杯",
            target_date=date(2026, 9, 1),
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

        self.save_goal()
        self.assertEqual(6, self.store_a.get(10).goal.target_award_id)
        self.assertEqual(6, self.store_b.get(10).goal.target_award_id)

    def test_cross_instance_forget_is_immediate(self):
        self.save_goal()

        result = self.store_b.forget(user_id=10, scope="goal")

        self.assertTrue(result.applied)
        self.assertIsNone(self.store_a.get(10).goal)


if __name__ == "__main__":
    unittest.main()
