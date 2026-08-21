from __future__ import annotations

import threading
import unittest
from datetime import datetime, timedelta, timezone

from app.confirmation_store import ConfirmationStatus, ConfirmationStore


class ConfirmationStoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 8, 21, 8, 0, tzinfo=timezone.utc)
        self.counter = 0

        def token_factory() -> str:
            self.counter += 1
            return f"confirmation-token-{self.counter:04d}"

        self.store = ConfirmationStore(
            ttl_seconds=120,
            clock=lambda: self.now,
            token_factory=token_factory,
        )

    def create(self, session_id: str = "session-a"):
        return self.store.create(
            user_id=10,
            session_id=session_id,
            award_id=6,
            award_name="手表",
            current_points=300,
            required_points=200,
            request_id="request-001",
        )

    def test_claim_is_bound_to_user_and_session(self):
        record = self.create()

        self.assertEqual(
            "CONFIRMATION_NOT_FOUND",
            self.store.claim(
                record.confirmation_id,
                user_id=11,
                session_id="session-a",
                request_id="request-002",
            ).code,
        )
        self.assertEqual(
            "CONFIRMATION_NOT_FOUND",
            self.store.claim(
                record.confirmation_id,
                user_id=10,
                session_id="session-b",
                request_id="request-002",
            ).code,
        )
        self.assertTrue(
            self.store.claim(
                record.confirmation_id,
                user_id=10,
                session_id="session-a",
                request_id="request-002",
            ).claimed
        )

    def test_expired_confirmation_cannot_be_claimed(self):
        record = self.create()
        self.now += timedelta(seconds=121)

        result = self.store.claim(
            record.confirmation_id,
            user_id=10,
            session_id="session-a",
            request_id="request-002",
        )

        self.assertEqual("CONFIRMATION_EXPIRED", result.code)
        self.assertEqual(
            ConfirmationStatus.EXPIRED,
            self.store.snapshot(record.confirmation_id).status,
        )

        # 即使 health/stats 已提前清理过期状态，用户仍应得到准确的“已过期”。
        self.store.stats()
        self.assertEqual(
            "CONFIRMATION_EXPIRED",
            self.store.claim(
                record.confirmation_id,
                user_id=10,
                session_id="session-a",
                request_id="request-003",
            ).code,
        )

    def test_new_preparation_invalidates_old_pending_confirmation(self):
        old = self.create()
        new = self.create()

        self.assertEqual(
            ConfirmationStatus.CANCELLED,
            self.store.snapshot(old.confirmation_id).status,
        )
        self.assertEqual(ConfirmationStatus.PREPARED, new.status)

    def test_pending_summary_is_scoped_and_expired_without_exposing_other_sessions(self):
        record = self.create()

        self.assertEqual(
            record.confirmation_id,
            self.store.pending_for(user_id=10, session_id="session-a").confirmation_id,
        )
        self.assertIsNone(self.store.pending_for(user_id=11, session_id="session-a"))
        self.assertIsNone(self.store.pending_for(user_id=10, session_id="session-b"))

        self.now += timedelta(seconds=121)
        self.assertIsNone(self.store.pending_for(user_id=10, session_id="session-a"))

    def test_concurrent_claim_allows_exactly_one_winner(self):
        record = self.create()
        barrier = threading.Barrier(12)
        results: list[bool] = []
        lock = threading.Lock()

        def claim() -> None:
            barrier.wait()
            won = self.store.claim(
                record.confirmation_id,
                user_id=10,
                session_id="session-a",
                request_id="request-concurrent",
            ).claimed
            with lock:
                results.append(won)

        threads = [threading.Thread(target=claim) for _ in range(12)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(1, sum(results))
        self.assertEqual(11, len(results) - sum(results))

    def test_same_request_cannot_prepare_and_confirm(self):
        record = self.create()

        result = self.store.claim(
            record.confirmation_id,
            user_id=10,
            session_id="session-a",
            request_id="request-001",
        )

        self.assertEqual("CONFIRMATION_REQUIRES_NEW_TURN", result.code)
        self.assertEqual(
            ConfirmationStatus.PREPARED,
            self.store.snapshot(record.confirmation_id).status,
        )
