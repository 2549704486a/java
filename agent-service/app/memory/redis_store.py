from __future__ import annotations

from datetime import date, datetime, timezone
import uuid

import redis

from app.memory.store import (
    ForgetScope,
    GrowthMemoryStoreBackend,
    MemoryType,
    MemoryChangeResult,
    MemoryWriteResult,
    _clean_normalized_data,
    _clean_text,
    _same_memory,
    _scope_memory_types,
    build_memory_key,
    business_date,
)
from app.models import GrowthMemoryData, MemoryItem, RedemptionGoalData, UserPreferenceData


class RedisGrowthMemoryStore(GrowthMemoryStoreBackend):
    """使用 Redis 保存跨会话目标和偏好，写操作直接落到用户维度的记录。"""

    def __init__(
        self,
        client: redis.Redis,
        *,
        key_prefix: str = "agent:growth:memory",
    ) -> None:
        self._client = client
        self._prefix = key_prefix.strip().rstrip(":")
        if not self._prefix:
            raise ValueError("Redis 长期记忆 key prefix 不能为空")

    @classmethod
    def from_url(cls, url: str, **kwargs) -> "RedisGrowthMemoryStore":
        client = redis.Redis.from_url(
            url,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
            health_check_interval=30,
        )
        client.ping()
        return cls(client, **kwargs)

    def get(self, user_id: int) -> GrowthMemoryData:
        goal_raw, preferences_raw = self._client.mget(
            self._goal_key(user_id),
            self._preferences_key(user_id),
        )
        goal = RedemptionGoalData.model_validate_json(goal_raw) if goal_raw else None
        preferences = (
            UserPreferenceData.model_validate_json(preferences_raw)
            if preferences_raw
            else None
        )
        if goal is not None:
            status = "ACTIVE" if goal.target_date >= business_date(self._redis_now()) else "EXPIRED"
            goal = goal.model_copy(update={"status": status})
        memories = [
            MemoryItem.model_validate_json(raw)
            for raw in self._client.hvals(self._items_key(user_id))
        ]
        memories.sort(key=lambda item: item.updated_at, reverse=True)
        return GrowthMemoryData(
            goal=goal,
            preferences=preferences,
            memories=memories,
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
        cleaned_text = _clean_text(raw_text, limit=500)
        cleaned_data = _clean_normalized_data(normalized_data or {})
        memory_key = build_memory_key(memory_type, cleaned_text, cleaned_data)
        key = self._items_key(user_id)
        while True:
            try:
                with self._client.pipeline() as pipe:
                    pipe.watch(key)
                    raw = pipe.hget(key, memory_key)
                    existing = MemoryItem.model_validate_json(raw) if raw else None
                    if existing is not None and _same_memory(
                        existing, cleaned_text, cleaned_data
                    ):
                        pipe.unwatch()
                        return MemoryWriteResult(
                            applied=False,
                            action="NOOP",
                            code="MEMORY_UNCHANGED",
                            message="这条长期记忆已经存在",
                            memory=existing,
                            current=self.get(user_id),
                        )

                    now = self._redis_now()
                    action = "ADD"
                    history_value = None
                    if existing is not None:
                        old_polarity = str(existing.normalized_data.get("polarity", ""))
                        new_polarity = str(cleaned_data.get("polarity", ""))
                        action = (
                            "SUPERSEDE"
                            if old_polarity
                            and new_polarity
                            and old_polarity != new_polarity
                            else "UPDATE"
                        )
                        history_value = existing.model_copy(
                            update={
                                "status": "SUPERSEDED",
                                "valid_to": now,
                                "updated_at": now,
                            }
                        ).model_dump_json(by_alias=True)
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
                    pipe.multi()
                    if history_value is not None:
                        pipe.rpush(self._history_key(user_id), history_value)
                    pipe.hset(key, memory_key, item.model_dump_json(by_alias=True))
                    pipe.execute()
                    return MemoryWriteResult(
                        applied=True,
                        action=action,
                        code={
                            "ADD": "MEMORY_ADDED",
                            "UPDATE": "MEMORY_UPDATED",
                            "SUPERSEDE": "MEMORY_SUPERSEDED",
                        }[action],
                        message={
                            "ADD": "已保存长期记忆",
                            "UPDATE": "已更新长期记忆",
                            "SUPERSEDE": "已用新的表达替代旧记忆",
                        }[action],
                        memory=item,
                        current=self.get(user_id),
                    )
            except redis.WatchError:
                continue

    def save_goal(
        self,
        *,
        user_id: int,
        source_session: str,
        target_award_id: int,
        target_award_name: str,
        target_date: date,
    ) -> MemoryChangeResult:
        key = self._goal_key(user_id)
        while True:
            try:
                with self._client.pipeline() as pipe:
                    pipe.watch(key)
                    raw = pipe.get(key)
                    existing = RedemptionGoalData.model_validate_json(raw) if raw else None
                    now = self._redis_now()
                    goal = RedemptionGoalData(
                        userId=user_id,
                        targetAwardId=target_award_id,
                        targetAwardName=target_award_name,
                        targetDate=target_date,
                        status="ACTIVE" if target_date >= business_date(now) else "EXPIRED",
                        createdAt=existing.created_at if existing else now,
                        updatedAt=now,
                        sourceSession=source_session,
                    )
                    pipe.multi()
                    pipe.set(key, goal.model_dump_json(by_alias=True))
                    pipe.execute()
                    return self._result(
                        True,
                        "REDEMPTION_GOAL_SAVED",
                        "已保存兑换目标",
                        user_id,
                    )
            except redis.WatchError:
                continue

    def replace_preferences(
        self,
        *,
        user_id: int,
        source_session: str,
        preferred_categories: list[str],
        disliked_categories: list[str],
        task_preferences: list[str],
    ) -> MemoryChangeResult:
        key = self._preferences_key(user_id)
        while True:
            try:
                with self._client.pipeline() as pipe:
                    pipe.watch(key)
                    raw = pipe.get(key)
                    existing = UserPreferenceData.model_validate_json(raw) if raw else None
                    now = self._redis_now()
                    preferences = UserPreferenceData(
                        userId=user_id,
                        preferredCategories=preferred_categories,
                        dislikedCategories=disliked_categories,
                        taskPreferences=task_preferences,
                        createdAt=existing.created_at if existing else now,
                        updatedAt=now,
                        sourceSession=source_session,
                    )
                    pipe.multi()
                    pipe.set(key, preferences.model_dump_json(by_alias=True))
                    pipe.execute()
                    return self._result(
                        True,
                        "USER_PREFERENCES_SAVED",
                        "已保存长期偏好",
                        user_id,
                    )
            except redis.WatchError:
                continue

    def forget(self, *, user_id: int, scope: ForgetScope) -> MemoryChangeResult:
        keys = []
        if scope in {"goal", "all"}:
            keys.append(self._goal_key(user_id))
        if scope in {"preferences", "all"}:
            keys.append(self._preferences_key(user_id))
        removed = int(self._client.delete(*keys)) if keys else 0
        memory_types = _scope_memory_types(scope)
        item_key = self._items_key(user_id)
        memory_fields = [
            field
            for field, raw in self._client.hgetall(item_key).items()
            if MemoryItem.model_validate_json(raw).memory_type in memory_types
        ]
        if memory_fields:
            removed += int(self._client.hdel(item_key, *memory_fields))
        return self._result(
            removed > 0,
            "GROWTH_MEMORY_FORGOTTEN" if removed else "NOTHING_TO_FORGET",
            "已遗忘指定的长期记忆" if removed else "对应范围内没有已保存的长期记忆",
            user_id,
        )

    def stats(self) -> dict[str, int]:
        return {
            "goals": sum(1 for _ in self._client.scan_iter(match=f"{self._prefix}:user:*:goal")),
            "preferences": sum(
                1 for _ in self._client.scan_iter(match=f"{self._prefix}:user:*:preferences")
            ),
            "memories": sum(
                self._client.hlen(key)
                for key in self._client.scan_iter(match=f"{self._prefix}:user:*:items")
            ),
        }

    def clear(self) -> None:
        keys = list(self._client.scan_iter(match=f"{self._prefix}:*"))
        if keys:
            self._client.delete(*keys)

    def close(self) -> None:
        self._client.close()

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

    def _redis_now(self) -> datetime:
        seconds, microseconds = self._client.time()
        return datetime.fromtimestamp(
            float(seconds) + float(microseconds) / 1_000_000,
            tz=timezone.utc,
        )

    def _goal_key(self, user_id: int) -> str:
        return f"{self._prefix}:user:{user_id}:goal"

    def _preferences_key(self, user_id: int) -> str:
        return f"{self._prefix}:user:{user_id}:preferences"

    def _items_key(self, user_id: int) -> str:
        return f"{self._prefix}:user:{user_id}:items"

    def _history_key(self, user_id: int) -> str:
        return f"{self._prefix}:user:{user_id}:history"
