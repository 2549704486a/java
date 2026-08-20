from __future__ import annotations

import secrets
import threading
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from enum import Enum


class ConfirmationStatus(str, Enum):
    PREPARED = "PREPARED"
    EXECUTING = "EXECUTING"
    PROCESSING = "PROCESSING"
    REJECTED = "REJECTED"
    UNKNOWN = "UNKNOWN"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True)
class ConfirmationRecord:
    confirmation_id: str
    user_id: int
    session_id: str
    award_id: int
    request_id: str
    status: ConfirmationStatus
    created_at: datetime
    expires_at: datetime
    result_code: str | None = None


@dataclass(frozen=True)
class ClaimResult:
    code: str
    record: ConfirmationRecord | None = None

    @property
    def claimed(self) -> bool:
        return self.record is not None


class ConfirmationStore:
    """带 TTL 的进程内确认存储；锁内完成检查与占用，防止重复写入。"""

    def __init__(
        self,
        ttl_seconds: int = 120,
        capacity: int = 10_000,
        clock: Callable[[], datetime] | None = None,
        token_factory: Callable[[], str] | None = None,
    ) -> None:
        self._ttl = timedelta(seconds=max(1, ttl_seconds))
        self._capacity = max(1, capacity)
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._token_factory = token_factory or (lambda: secrets.token_urlsafe(32))
        self._records: dict[str, ConfirmationRecord] = {}
        self._lock = threading.Lock()

    def create(
        self,
        *,
        user_id: int,
        session_id: str,
        award_id: int,
        request_id: str,
    ) -> ConfirmationRecord:
        now = self._now()
        with self._lock:
            self._expire_locked(now)
            self._cancel_pending_locked(user_id, session_id)
            self._make_room_locked()
            confirmation_id = self._unique_token_locked()
            record = ConfirmationRecord(
                confirmation_id=confirmation_id,
                user_id=user_id,
                session_id=session_id,
                award_id=award_id,
                request_id=request_id,
                status=ConfirmationStatus.PREPARED,
                created_at=now,
                expires_at=now + self._ttl,
            )
            self._records[confirmation_id] = record
            return record

    def claim(
        self,
        confirmation_id: str,
        *,
        user_id: int,
        session_id: str,
        request_id: str,
    ) -> ClaimResult:
        now = self._now()
        with self._lock:
            record = self._records.get(confirmation_id)
            # 对跨用户、跨会话和随机令牌统一返回不存在，避免泄露凭证是否真实存在。
            if (
                record is None
                or record.user_id != user_id
                or record.session_id != session_id
            ):
                return ClaimResult("CONFIRMATION_NOT_FOUND")
            if record.status == ConfirmationStatus.PREPARED and now >= record.expires_at:
                expired = replace(record, status=ConfirmationStatus.EXPIRED)
                self._records[confirmation_id] = expired
                return ClaimResult("CONFIRMATION_EXPIRED")
            if record.status == ConfirmationStatus.EXPIRED:
                return ClaimResult("CONFIRMATION_EXPIRED")
            if record.status != ConfirmationStatus.PREPARED:
                return ClaimResult("CONFIRMATION_ALREADY_USED")
            # 用户必须先收到摘要，再通过后续请求确认；禁止模型在同一轮自行连调。
            if record.request_id == request_id:
                return ClaimResult("CONFIRMATION_REQUIRES_NEW_TURN")

            executing = replace(record, status=ConfirmationStatus.EXECUTING)
            self._records[confirmation_id] = executing
            return ClaimResult("CONFIRMATION_CLAIMED", executing)

    def finish(
        self,
        confirmation_id: str,
        status: ConfirmationStatus,
        result_code: str,
    ) -> ConfirmationRecord | None:
        if status not in {
            ConfirmationStatus.PROCESSING,
            ConfirmationStatus.REJECTED,
            ConfirmationStatus.UNKNOWN,
        }:
            raise ValueError(f"不允许的完成状态：{status}")
        with self._lock:
            record = self._records.get(confirmation_id)
            if record is None or record.status != ConfirmationStatus.EXECUTING:
                return None
            finished = replace(record, status=status, result_code=result_code)
            self._records[confirmation_id] = finished
            return finished

    def cancel_pending(self, *, user_id: int, session_id: str) -> int:
        with self._lock:
            return self._cancel_pending_locked(user_id, session_id)

    def cancel_pending_by_session(self, session_id: str) -> int:
        with self._lock:
            cancelled = 0
            for key, record in list(self._records.items()):
                if (
                    record.session_id == session_id
                    and record.status == ConfirmationStatus.PREPARED
                ):
                    self._records[key] = replace(
                        record, status=ConfirmationStatus.CANCELLED
                    )
                    cancelled += 1
            return cancelled

    def snapshot(self, confirmation_id: str) -> ConfirmationRecord | None:
        with self._lock:
            return self._records.get(confirmation_id)

    def stats(self) -> dict[str, int]:
        now = self._now()
        with self._lock:
            self._expire_locked(now)
            return {
                "total": len(self._records),
                "pending": sum(
                    record.status == ConfirmationStatus.PREPARED
                    for record in self._records.values()
                ),
                "executing": sum(
                    record.status == ConfirmationStatus.EXECUTING
                    for record in self._records.values()
                ),
            }

    def clear(self) -> None:
        with self._lock:
            self._records.clear()

    def _cancel_pending_locked(self, user_id: int, session_id: str) -> int:
        cancelled = 0
        for key, record in list(self._records.items()):
            if (
                record.user_id == user_id
                and record.session_id == session_id
                and record.status == ConfirmationStatus.PREPARED
            ):
                self._records[key] = replace(
                    record, status=ConfirmationStatus.CANCELLED
                )
                cancelled += 1
        return cancelled

    def _expire_locked(self, now: datetime) -> None:
        for key, record in list(self._records.items()):
            if record.status == ConfirmationStatus.PREPARED and now >= record.expires_at:
                self._records[key] = replace(record, status=ConfirmationStatus.EXPIRED)

    def _make_room_locked(self) -> None:
        if len(self._records) < self._capacity:
            return
        removable = sorted(
            (
                record
                for record in self._records.values()
                if record.status != ConfirmationStatus.EXECUTING
            ),
            key=lambda record: record.created_at,
        )
        if not removable:
            raise RuntimeError("确认存储容量已满，请稍后再试")
        self._records.pop(removable[0].confirmation_id, None)

    def _unique_token_locked(self) -> str:
        for _ in range(10):
            token = self._token_factory()
            if token and token not in self._records:
                return token
        raise RuntimeError("无法生成唯一兑换确认凭证")

    def _now(self) -> datetime:
        now = self._clock()
        return now if now.tzinfo is not None else now.replace(tzinfo=timezone.utc)
