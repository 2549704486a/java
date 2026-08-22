from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone
from typing import Literal, Protocol

from pydantic import BaseModel

from app.models import GrowthMemoryData, RedemptionGoalData, UserPreferenceData


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


BUSINESS_TIME_ZONE = timezone(timedelta(hours=8))
ForgetScope = Literal["goal", "preferences", "all"]


def business_date(value: datetime) -> date:
    return value.astimezone(BUSINESS_TIME_ZONE).date()


class MemoryChangeResult(BaseModel):
    applied: bool
    code: str
    message: str
    memory: GrowthMemoryData


class GrowthMemoryStoreBackend(Protocol):
    def get(self, user_id: int) -> GrowthMemoryData: ...

    def save_goal(
        self,
        *,
        user_id: int,
        source_session: str,
        target_award_id: int,
        target_award_name: str,
        target_date: date,
    ) -> MemoryChangeResult: ...

    def replace_preferences(
        self,
        *,
        user_id: int,
        source_session: str,
        preferred_categories: list[str],
        disliked_categories: list[str],
        task_preferences: list[str],
    ) -> MemoryChangeResult: ...

    def forget(self, *, user_id: int, scope: ForgetScope) -> MemoryChangeResult: ...

    def stats(self) -> dict[str, int]: ...

    def close(self) -> None: ...


class GrowthMemoryStore:
    """单进程长期记忆实现，主要用于测试和不依赖 Redis 的本地演示。"""

    def __init__(
        self,
        *,
        now_provider: Callable[[], datetime] = utc_now,
    ) -> None:
        self._now = now_provider
        self._goals: dict[int, RedemptionGoalData] = {}
        self._preferences: dict[int, UserPreferenceData] = {}
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

    def save_goal(
        self,
        *,
        user_id: int,
        source_session: str,
        target_award_id: int,
        target_award_name: str,
        target_date: date,
    ) -> MemoryChangeResult:
        with self._lock:
            now = self._now()
            existing = self._goals.get(user_id)
            self._goals[user_id] = RedemptionGoalData(
                userId=user_id,
                targetAwardId=target_award_id,
                targetAwardName=target_award_name,
                targetDate=target_date,
                status="ACTIVE" if target_date >= business_date(now) else "EXPIRED",
                createdAt=existing.created_at if existing else now,
                updatedAt=now,
                sourceSession=source_session,
            )
            return self._result(
                True,
                "REDEMPTION_GOAL_SAVED",
                "已保存兑换目标",
                user_id,
            )

    def replace_preferences(
        self,
        *,
        user_id: int,
        source_session: str,
        preferred_categories: list[str],
        disliked_categories: list[str],
        task_preferences: list[str],
    ) -> MemoryChangeResult:
        with self._lock:
            now = self._now()
            existing = self._preferences.get(user_id)
            self._preferences[user_id] = UserPreferenceData(
                userId=user_id,
                preferredCategories=preferred_categories,
                dislikedCategories=disliked_categories,
                taskPreferences=task_preferences,
                createdAt=existing.created_at if existing else now,
                updatedAt=now,
                sourceSession=source_session,
            )
            return self._result(
                True,
                "USER_PREFERENCES_SAVED",
                "已保存长期偏好",
                user_id,
            )

    def forget(self, *, user_id: int, scope: ForgetScope) -> MemoryChangeResult:
        with self._lock:
            removed = False
            if scope in {"goal", "all"}:
                removed = self._goals.pop(user_id, None) is not None or removed
            if scope in {"preferences", "all"}:
                removed = self._preferences.pop(user_id, None) is not None or removed
            return self._result(
                removed,
                "GROWTH_MEMORY_FORGOTTEN" if removed else "NOTHING_TO_FORGET",
                "已遗忘指定的长期记忆" if removed else "对应范围内没有已保存的长期记忆",
                user_id,
            )

    def stats(self) -> dict[str, int]:
        with self._lock:
            return {
                "goals": len(self._goals),
                "preferences": len(self._preferences),
            }

    def close(self) -> None:
        return None

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
