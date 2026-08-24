from __future__ import annotations

import threading
import re
import uuid
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone
from typing import Literal, Protocol

from pydantic import BaseModel

from app.models import GrowthMemoryData, MemoryItem, RedemptionGoalData, UserPreferenceData


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


BUSINESS_TIME_ZONE = timezone(timedelta(hours=8))
MemoryType = Literal["preference", "goal", "profile", "episode"]
MemoryAction = Literal["ADD", "UPDATE", "SUPERSEDE", "NOOP"]
ForgetScope = Literal["goal", "preferences", "profile", "all"]


def business_date(value: datetime) -> date:
    return value.astimezone(BUSINESS_TIME_ZONE).date()


class MemoryChangeResult(BaseModel):
    applied: bool
    code: str
    message: str
    memory: GrowthMemoryData


class MemoryWriteResult(BaseModel):
    applied: bool
    action: MemoryAction
    code: str
    message: str
    memory: MemoryItem
    current: GrowthMemoryData


class GrowthMemoryStoreBackend(Protocol):
    def get(self, user_id: int) -> GrowthMemoryData: ...

    def remember(
        self,
        *,
        user_id: int,
        source_session: str,
        memory_type: MemoryType,
        raw_text: str,
        normalized_data: dict | None = None,
        source_message_id: str | None = None,
    ) -> MemoryWriteResult: ...

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
        self._memory_items: dict[int, dict[str, MemoryItem]] = {}
        self._memory_history: list[MemoryItem] = []
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
                memories=self._active_memories(user_id),
            )

    def remember(
        self,
        *,
        user_id: int,
        source_session: str,
        memory_type: MemoryType,
        raw_text: str,
        normalized_data: dict | None = None,
        source_message_id: str | None = None,
    ) -> MemoryWriteResult:
        with self._lock:
            return self._remember_locked(
                user_id=user_id,
                source_session=source_session,
                memory_type=memory_type,
                raw_text=raw_text,
                normalized_data=normalized_data or {},
                source_message_id=source_message_id,
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
            self._remember_locked(
                user_id=user_id,
                source_session=source_session,
                memory_type="goal",
                raw_text=f"计划在 {target_date.isoformat()} 兑换 {target_award_name}",
                normalized_data={
                    "subject": f"award:{target_award_id}",
                    "target": target_award_name,
                    "awardId": target_award_id,
                    "targetDate": target_date.isoformat(),
                },
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
            items = self._memory_items.setdefault(user_id, {})
            for key in [key for key, item in items.items() if item.memory_type == "preference"]:
                del items[key]
            for value in preferred_categories:
                self._remember_locked(
                    user_id=user_id,
                    source_session=source_session,
                    memory_type="preference",
                    raw_text=f"喜欢 {value}",
                    normalized_data={"subject": value, "polarity": "LIKE"},
                )
            for value in disliked_categories:
                self._remember_locked(
                    user_id=user_id,
                    source_session=source_session,
                    memory_type="preference",
                    raw_text=f"不喜欢 {value}",
                    normalized_data={"subject": value, "polarity": "DISLIKE"},
                )
            for value in task_preferences:
                self._remember_locked(
                    user_id=user_id,
                    source_session=source_session,
                    memory_type="preference",
                    raw_text=f"偏好 {value} 任务",
                    normalized_data={
                        "subject": value,
                        "polarity": "LIKE",
                        "preferenceKind": "task",
                    },
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
            memory_types = _scope_memory_types(scope)
            items = self._memory_items.get(user_id, {})
            for key in [
                key for key, item in items.items() if item.memory_type in memory_types
            ]:
                del items[key]
                removed = True
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
                "memories": sum(len(items) for items in self._memory_items.values()),
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

    def _remember_locked(
        self,
        *,
        user_id: int,
        source_session: str,
        memory_type: MemoryType,
        raw_text: str,
        normalized_data: dict,
        source_message_id: str | None = None,
    ) -> MemoryWriteResult:
        now = self._now()
        cleaned_text = _clean_text(raw_text, limit=500)
        cleaned_data = _clean_normalized_data(normalized_data)
        memory_key = build_memory_key(memory_type, cleaned_text, cleaned_data)
        items = self._memory_items.setdefault(user_id, {})
        existing = items.get(memory_key)

        if existing is not None and _same_memory(existing, cleaned_text, cleaned_data):
            return MemoryWriteResult(
                applied=False,
                action="NOOP",
                code="MEMORY_UNCHANGED",
                message="这条长期记忆已经存在",
                memory=existing.model_copy(deep=True),
                current=self.get(user_id),
            )

        action: MemoryAction = "ADD"
        if existing is not None:
            old_polarity = str(existing.normalized_data.get("polarity", ""))
            new_polarity = str(cleaned_data.get("polarity", ""))
            action = (
                "SUPERSEDE"
                if old_polarity and new_polarity and old_polarity != new_polarity
                else "UPDATE"
            )
            self._memory_history.append(
                existing.model_copy(
                    update={"status": "SUPERSEDED", "valid_to": now, "updated_at": now}
                )
            )

        item = MemoryItem(
            memoryId=uuid.uuid4().hex,
            userId=user_id,
            memoryType=memory_type,
            memoryKey=memory_key,
            rawText=cleaned_text,
            normalizedData=cleaned_data,
            status="ACTIVE",
            validFrom=now,
            validTo=None,
            sourceSession=source_session,
            sourceMessageId=source_message_id,
            createdAt=now,
            updatedAt=now,
        )
        items[memory_key] = item
        code = {
            "ADD": "MEMORY_ADDED",
            "UPDATE": "MEMORY_UPDATED",
            "SUPERSEDE": "MEMORY_SUPERSEDED",
        }[action]
        message = {
            "ADD": "已保存长期记忆",
            "UPDATE": "已更新长期记忆",
            "SUPERSEDE": "已用新的表达替代旧记忆",
        }[action]
        return MemoryWriteResult(
            applied=True,
            action=action,
            code=code,
            message=message,
            memory=item.model_copy(deep=True),
            current=self.get(user_id),
        )

    def _active_memories(self, user_id: int) -> list[MemoryItem]:
        items = self._memory_items.get(user_id, {}).values()
        return sorted(
            (item.model_copy(deep=True) for item in items if item.status == "ACTIVE"),
            key=lambda item: item.updated_at,
            reverse=True,
        )


def build_memory_key(
    memory_type: MemoryType,
    raw_text: str,
    normalized_data: dict,
) -> str:
    """使用可读的业务身份键去重；结构化字段缺失时退化为原文。"""
    identity = (
        normalized_data.get("subject")
        or normalized_data.get("target")
        or raw_text
    )
    normalized_identity = _clean_text(str(identity), limit=220).casefold()
    return f"{memory_type}:{normalized_identity}"


def _clean_text(value: str, *, limit: int) -> str:
    cleaned = re.sub(r"\s+", " ", value.strip())[:limit]
    if not cleaned:
        raise ValueError("长期记忆原文不能为空")
    return cleaned


def _clean_normalized_data(value: dict) -> dict:
    result = {}
    for key, item in value.items():
        if item is None:
            continue
        if isinstance(item, str):
            cleaned = re.sub(r"\s+", " ", item.strip())[:200]
            if cleaned:
                result[str(key)[:80]] = cleaned
        elif isinstance(item, (bool, int, float)):
            result[str(key)[:80]] = item
    return result


def _same_memory(existing: MemoryItem, raw_text: str, normalized_data: dict) -> bool:
    if normalized_data:
        return existing.normalized_data == normalized_data
    return re.sub(r"\s+", " ", existing.raw_text).casefold() == raw_text.casefold()


def _scope_memory_types(scope: ForgetScope) -> set[MemoryType]:
    if scope == "all":
        return {"preference", "goal", "profile", "episode"}
    if scope == "preferences":
        return {"preference"}
    return {scope}
