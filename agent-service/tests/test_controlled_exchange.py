from __future__ import annotations

import threading
import unittest

from app.api_client import BusinessApiError
from app.confirmation_store import ConfirmationStatus, ConfirmationStore
from app.models import ToolEnvelope
from app.skills.controlled_exchange import ControlledExchangeSkill


class ExchangeClient:
    def __init__(self) -> None:
        self.submit_calls = 0
        self.submit_result = ToolEnvelope(
            success=True,
            code="EXCHANGE_PROCESSING",
            data=None,
            message="处理中",
            retryable=False,
        )
        self.submit_error: BusinessApiError | None = None
        self._lock = threading.Lock()

    def check_exchange_eligibility(self, user_id: int, award_id: int):
        return ToolEnvelope(
            success=True,
            code="ELIGIBILITY_CHECKED",
            data={
                "userId": user_id,
                "awardId": award_id,
                "eligible": True,
                "reasonCode": "ELIGIBLE",
                "reason": "满足兑换条件",
                "currentPoints": 300,
                "requiredPoints": 200,
                "pointsGap": 0,
            },
            message="查询成功",
            retryable=False,
        )

    def get_award_detail(self, award_id: int):
        return ToolEnvelope(
            success=True,
            code="AWARD_FOUND",
            data={
                "awardId": award_id,
                "name": "手表",
                "requiredPoints": 200,
                "inventory": 10,
            },
            message="查询成功",
            retryable=False,
        )

    def submit_exchange(self, **kwargs):
        with self._lock:
            self.submit_calls += 1
        if self.submit_error is not None:
            raise self.submit_error
        return self.submit_result


class ControlledExchangeSkillTest(unittest.TestCase):
    def setUp(self) -> None:
        self.client = ExchangeClient()
        self.store = ConfirmationStore(token_factory=lambda: "x" * 32)
        self.skill = ControlledExchangeSkill(self.client, self.store)

    def prepare(self):
        return self.skill.prepare(
            user_id=10,
            session_id="session-a",
            request_id="request-prepare",
            award_id=6,
        )

    def test_prepare_only_creates_confirmation_without_writing(self):
        result = self.prepare()

        self.assertEqual("EXCHANGE_CONFIRMATION_REQUIRED", result.code)
        self.assertEqual(0, self.client.submit_calls)
        self.assertEqual("手表", result.data["awardName"])
        self.assertEqual(100, result.data["remainingPoints"])

    def test_repeated_confirmation_calls_java_exactly_once(self):
        confirmation_id = self.prepare().data["confirmationId"]

        first = self.skill.confirm(
            user_id=10,
            session_id="session-a",
            request_id="request-confirm-1",
            confirmation_id=confirmation_id,
        )
        second = self.skill.confirm(
            user_id=10,
            session_id="session-a",
            request_id="request-confirm-2",
            confirmation_id=confirmation_id,
        )

        self.assertEqual("EXCHANGE_PROCESSING", first.code)
        self.assertEqual("CONFIRMATION_ALREADY_USED", second.code)
        self.assertEqual(1, self.client.submit_calls)

    def test_concurrent_confirmation_calls_java_exactly_once(self):
        confirmation_id = self.prepare().data["confirmationId"]
        barrier = threading.Barrier(10)
        codes: list[str] = []
        lock = threading.Lock()

        def confirm() -> None:
            barrier.wait()
            result = self.skill.confirm(
                user_id=10,
                session_id="session-a",
                request_id="request-concurrent",
                confirmation_id=confirmation_id,
            )
            with lock:
                codes.append(result.code)

        threads = [threading.Thread(target=confirm) for _ in range(10)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(1, self.client.submit_calls)
        self.assertEqual(1, codes.count("EXCHANGE_PROCESSING"))
        self.assertEqual(9, codes.count("CONFIRMATION_ALREADY_USED"))

    def test_unknown_submission_is_terminal_and_not_retried(self):
        confirmation_id = self.prepare().data["confirmationId"]
        self.client.submit_error = BusinessApiError(
            "SUBMISSION_UNKNOWN", "超时", False
        )

        result = self.skill.confirm(
            user_id=10,
            session_id="session-a",
            request_id="request-unknown",
            confirmation_id=confirmation_id,
        )

        self.assertEqual("SUBMISSION_UNKNOWN", result.code)
        self.assertFalse(result.retryable)
        self.assertEqual(1, self.client.submit_calls)
        self.assertEqual(
            ConfirmationStatus.UNKNOWN,
            self.store.snapshot(confirmation_id).status,
        )
