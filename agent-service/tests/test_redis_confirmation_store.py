from __future__ import annotations

import os
import threading
import time
import unittest
import uuid

from app.confirmation_store import ConfirmationStatus
from app.config import Settings
from app.redis_confirmation_store import RedisConfirmationStore
from app.runtime import build_confirmation_store


REDIS_URL = os.getenv(
    "EXCHANGE_CONFIRMATION_REDIS_URL",
    "redis://127.0.0.1:6379/0",
)
RUN_REDIS_TESTS = os.getenv("RUN_REDIS_INTEGRATION_TESTS") == "1"


@unittest.skipUnless(
    RUN_REDIS_TESTS,
    "设置 RUN_REDIS_INTEGRATION_TESTS=1 后运行 Redis 集成测试",
)
class RedisConfirmationStoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self.prefix = f"agent:test:confirmation:{uuid.uuid4().hex}"
        self.store_a = RedisConfirmationStore.from_url(
            REDIS_URL,
            key_prefix=self.prefix,
            ttl_seconds=120,
            retention_seconds=600,
        )
        self.store_b = RedisConfirmationStore.from_url(
            REDIS_URL,
            key_prefix=self.prefix,
            ttl_seconds=120,
            retention_seconds=600,
        )

    def tearDown(self) -> None:
        # 任一实例都能清理同一测试命名空间；正常运行时不会调用 clear。
        self.store_b.clear()
        self.store_a.close()
        self.store_b.close()

    def create(self, store=None, request_id: str = "request-prepare"):
        target = store or self.store_a
        return target.create(
            user_id=10,
            session_id="user:10:session:session-a",
            award_id=6,
            award_name="智能手表",
            current_points=3000,
            required_points=2500,
            request_id=request_id,
        )

    def test_record_and_pending_summary_are_shared_between_instances(self):
        record = self.create(self.store_a)

        snapshot = self.store_b.snapshot(record.confirmation_id)
        pending = self.store_b.pending_for(
            user_id=10,
            session_id="user:10:session:session-a",
        )

        self.assertEqual(record, snapshot)
        self.assertEqual(record.confirmation_id, pending.confirmation_id)

    def test_runtime_factory_builds_configured_redis_store(self):
        store = build_confirmation_store(
            Settings(
                exchange_confirmation_store="redis",
                exchange_confirmation_redis_url=REDIS_URL,
                exchange_confirmation_redis_prefix=self.prefix,
            )
        )
        try:
            self.assertIsInstance(store, RedisConfirmationStore)
            record = self.create(store)
            self.assertIsNotNone(self.store_b.snapshot(record.confirmation_id))
        finally:
            store.close()

    def test_new_preparation_cancels_old_record_across_instances(self):
        old = self.create(self.store_a, "request-old")
        new = self.create(self.store_b, "request-new")

        self.assertEqual(
            ConfirmationStatus.CANCELLED,
            self.store_a.snapshot(old.confirmation_id).status,
        )
        self.assertEqual(
            new.confirmation_id,
            self.store_a.pending_for(
                user_id=10,
                session_id="user:10:session:session-a",
            ).confirmation_id,
        )

    def test_cross_instance_concurrent_claim_has_exactly_one_winner(self):
        record = self.create()
        barrier = threading.Barrier(20)
        codes: list[str] = []
        lock = threading.Lock()

        def claim(index: int) -> None:
            barrier.wait()
            store = self.store_a if index % 2 == 0 else self.store_b
            result = store.claim(
                record.confirmation_id,
                user_id=10,
                session_id="user:10:session:session-a",
                request_id=f"request-confirm-{index}",
            )
            with lock:
                codes.append(result.code)

        threads = [threading.Thread(target=claim, args=(index,)) for index in range(20)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(1, codes.count("CONFIRMATION_CLAIMED"))
        self.assertEqual(19, codes.count("CONFIRMATION_ALREADY_USED"))
        self.assertEqual(
            ConfirmationStatus.EXECUTING,
            self.store_b.snapshot(record.confirmation_id).status,
        )

    def test_finish_is_visible_to_other_instance(self):
        record = self.create()
        claimed = self.store_a.claim(
            record.confirmation_id,
            user_id=10,
            session_id="user:10:session:session-a",
            request_id="request-confirm",
        )
        self.assertTrue(claimed.claimed)

        self.store_b.finish(
            record.confirmation_id,
            ConfirmationStatus.PROCESSING,
            "EXCHANGE_PROCESSING",
        )

        finished = self.store_a.snapshot(record.confirmation_id)
        self.assertEqual(ConfirmationStatus.PROCESSING, finished.status)
        self.assertEqual("EXCHANGE_PROCESSING", finished.result_code)

    def test_claim_preserves_identity_turn_and_expiration_rules(self):
        record = self.create()

        self.assertEqual(
            "CONFIRMATION_NOT_FOUND",
            self.store_b.claim(
                record.confirmation_id,
                user_id=11,
                session_id="user:10:session:session-a",
                request_id="request-confirm",
            ).code,
        )
        self.assertEqual(
            "CONFIRMATION_REQUIRES_NEW_TURN",
            self.store_b.claim(
                record.confirmation_id,
                user_id=10,
                session_id="user:10:session:session-a",
                request_id="request-prepare",
            ).code,
        )

        expiring_prefix = f"{self.prefix}:expiring"
        expiring_store = RedisConfirmationStore.from_url(
            REDIS_URL,
            key_prefix=expiring_prefix,
            ttl_seconds=1,
            retention_seconds=60,
        )
        try:
            expiring = self.create(expiring_store)
            time.sleep(1.05)
            self.assertEqual(
                "CONFIRMATION_EXPIRED",
                expiring_store.claim(
                    expiring.confirmation_id,
                    user_id=10,
                    session_id="user:10:session:session-a",
                    request_id="request-confirm",
                ).code,
            )
        finally:
            expiring_store.clear()
            expiring_store.close()

    def test_closing_one_instance_does_not_delete_shared_record(self):
        record = self.create(self.store_a)

        self.store_a.close()

        self.assertIsNotNone(self.store_b.snapshot(record.confirmation_id))
