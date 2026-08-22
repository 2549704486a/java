from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone
from enum import Enum
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from app.models import GrowthMemoryData, RedemptionGoalData, UserPreferenceData


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


BUSINESS_TIME_ZONE = timezone(timedelta(hours=8))


def business_date(value: datetime) -> date:
    return value.astimezone(BUSINESS_TIME_ZONE).date()


class MemoryChangeType(str, Enum):
    UPSERT_GOAL = "UPSERT_GOAL"
    REPLACE_PREFERENCES = "REPLACE_PREFERENCES"
    FORGET_GOAL = "FORGET_GOAL"
    FORGET_PREFERENCES = "FORGET_PREFERENCES"
    FORGET_ALL = "FORGET_ALL"


class PendingMemoryChange(BaseModel):
    model_config = ConfigDict(frozen=True)

    user_id: int
    session_id: str
    change_type: MemoryChangeType
    payload: dict[str, Any] = Field(default_factory=dict)
    summary: str
    created_at: datetime
    expires_at: datetime


class MemoryChangeResult(BaseModel):
    applied: bool
    code: str
    message: str
    memory: GrowthMemoryData | None = None


class GrowthMemoryStoreBackend(Protocol):
    def get(self, user_id: int) -> GrowthMemoryData: ...

    def prepare(
        self,
        *,
        user_id: int,
        session_id: str,
        change_type: MemoryChangeType,
        payload: dict[str, Any],
        summary: str,
    ) -> PendingMemoryChange: ...

    def pending_for(
        self,
        *,
        user_id: int,
        session_id: str,
    ) -> PendingMemoryChange | None: ...

    def confirm(self, *, user_id: int, session_id: str) -> MemoryChangeResult: ...

    def cancel_pending(self, *, user_id: int, session_id: str) -> int: ...

    def cancel_pending_by_session(self, session_id: str) -> int: ...

    def stats(self) -> dict[str, int]: ...

    def close(self) -> None: ...


class GrowthMemoryStore:
    """单进程实现，主要用于测试和不依赖 Redis 的本地演示。"""

    def __init__(
        self,
        *,
        pending_ttl_seconds: int = 120,
        now_provider: Callable[[], datetime] = utc_now,
    ) -> None:
        self._pending_ttl = timedelta(seconds=max(1, pending_ttl_seconds))
        self._now = now_provider
        self._goals: dict[int, RedemptionGoalData] = {}
        self._preferences: dict[int, UserPreferenceData] = {}
        self._pending: dict[str, PendingMemoryChange] = {}
        self._lock = threading.RLock()

    def get(self, user_id: int) -> GrowthMemoryData:
        with self._lock:
            goal = self._goals.get(user_id)
            preferences = self._preferences.get(user_id)
            return GrowthMemoryData(
                goal=self._with_current_goal_status(goal),
                preferences=(
                    preferences.model_copy(deep=True)
                    if preferences is not None
                    else None
                ),
            )

    def prepare(
        self,
        *,
        user_id: int,
        session_id: str,
        change_type: MemoryChangeType,
        payload: dict[str, Any],
        summary: str,
    ) -> PendingMemoryChange:
        now = self._now()
        pending = PendingMemoryChange(
            user_id=user_id,
            session_id=session_id,
            change_type=change_type,
            payload=payload,
            summary=summary,
            created_at=now,
            expires_at=now + self._pending_ttl,
        )
        with self._lock:
            self._pending[session_id] = pending
        return pending

    def pending_for(
        self,
        *,
        user_id: int,
        session_id: str,
    ) -> PendingMemoryChange | None:
        with self._lock:
            pending = self._pending.get(session_id)
            if pending is None or pending.user_id != user_id:
                return None
            if self._now() >= pending.expires_at:
                self._pending.pop(session_id, None)
                return None
            return pending

    def confirm(self, *, user_id: int, session_id: str) -> MemoryChangeResult:
        with self._lock:
            pending = self._pending.get(session_id)
            if pending is None or pending.user_id != user_id:
                return self._result(False, "MEMORY_CHANGE_NOT_FOUND", "当前没有待确认的记忆变更", user_id)
            if self._now() >= pending.expires_at:
                self._pending.pop(session_id, None)
                return self._result(False, "MEMORY_CHANGE_EXPIRED", "记忆变更确认已过期，请重新发起", user_id)

            self._apply(pending)
            self._pending.pop(session_id, None)
            return self._result(True, "MEMORY_CHANGE_APPLIED", "已按确认内容更新长期记忆", user_id)

    def cancel_pending(self, *, user_id: int, session_id: str) -> int:
        with self._lock:
            pending = self._pending.get(session_id)
            if pending is None or pending.user_id != user_id:
                return 0
            self._pending.pop(session_id, None)
            return 1

    def cancel_pending_by_session(self, session_id: str) -> int:
        with self._lock:
            return 1 if self._pending.pop(session_id, None) is not None else 0

    def stats(self) -> dict[str, int]:
        with self._lock:
            active_pending = sum(self._now() < item.expires_at for item in self._pending.values())
            return {
                "goals": len(self._goals),
                "preferences": len(self._preferences),
                "pending": active_pending,
            }

    def close(self) -> None:
        return None

    def _apply(self, pending: PendingMemoryChange) -> None:
        now = self._now()
        user_id = pending.user_id
        if pending.change_type == MemoryChangeType.UPSERT_GOAL:
            existing = self._goals.get(user_id)
            target_date = date.fromisoformat(str(pending.payload["target_date"]))
            self._goals[user_id] = RedemptionGoalData(
                userId=user_id,
                targetAwardId=int(pending.payload["target_award_id"]),
                targetAwardName=str(pending.payload["target_award_name"]),
                targetDate=target_date,
                status="ACTIVE" if target_date >= business_date(now) else "EXPIRED",
                createdAt=existing.created_at if existing else now,
                updatedAt=now,
                sourceSession=pending.session_id,
            )
        elif pending.change_type == MemoryChangeType.REPLACE_PREFERENCES:
            existing = self._preferences.get(user_id)
            self._preferences[user_id] = UserPreferenceData(
                userId=user_id,
                preferredCategories=pending.payload.get("preferred_categories", []),
                dislikedCategories=pending.payload.get("disliked_categories", []),
                taskPreferences=pending.payload.get("task_preferences", []),
                createdAt=existing.created_at if existing else now,
                updatedAt=now,
                sourceSession=pending.session_id,
            )
        elif pending.change_type == MemoryChangeType.FORGET_GOAL:
            self._goals.pop(user_id, None)
        elif pending.change_type == MemoryChangeType.FORGET_PREFERENCES:
            self._preferences.pop(user_id, None)
        elif pending.change_type == MemoryChangeType.FORGET_ALL:
            self._goals.pop(user_id, None)
            self._preferences.pop(user_id, None)

    def _with_current_goal_status(
        self,
        goal: RedemptionGoalData | None,
    ) -> RedemptionGoalData | None:
        if goal is None:
            return None
        status = "ACTIVE" if goal.target_date >= business_date(self._now()) else "EXPIRED"
        return goal.model_copy(update={"status": status})

    def _result(
        self,
        applied: bool,
        code: str,
        message: str,
        user_id: int,
    ) -> MemoryChangeResult:
        return MemoryChangeResult(
            applied=applied,
            code=code,
            message=message,
            memory=self.get(user_id),
        )
