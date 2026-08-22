from __future__ import annotations

from datetime import date, datetime, timezone

import redis

from app.growth_memory_store import (
    ForgetScope,
    GrowthMemoryStoreBackend,
    MemoryChangeResult,
    business_date,
)
from app.models import GrowthMemoryData, RedemptionGoalData, UserPreferenceData


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
        return GrowthMemoryData(goal=goal, preferences=preferences)

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
