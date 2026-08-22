from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import redis

from app.growth_memory_store import (
    business_date,
    GrowthMemoryStoreBackend,
    MemoryChangeResult,
    MemoryChangeType,
    PendingMemoryChange,
)
from app.models import GrowthMemoryData, RedemptionGoalData, UserPreferenceData


class RedisGrowthMemoryStore(GrowthMemoryStoreBackend):
    """使用 Redis 保存跨会话记忆，并通过 WATCH/MULTI 原子消费确认草稿。"""

    def __init__(
        self,
        client: redis.Redis,
        *,
        pending_ttl_seconds: int = 120,
        key_prefix: str = "agent:growth:memory",
    ) -> None:
        self._client = client
        self._pending_ttl = timedelta(seconds=max(1, pending_ttl_seconds))
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

    def prepare(
        self,
        *,
        user_id: int,
        session_id: str,
        change_type: MemoryChangeType,
        payload: dict,
        summary: str,
    ) -> PendingMemoryChange:
        now = self._redis_now()
        pending = PendingMemoryChange(
            user_id=user_id,
            session_id=session_id,
            change_type=change_type,
            payload=payload,
            summary=summary,
            created_at=now,
            expires_at=now + self._pending_ttl,
        )
        # 多保留一分钟，使确认时可以区分“已过期”和“从未创建”。
        retention_ms = int((self._pending_ttl.total_seconds() + 60) * 1000)
        self._client.set(
            self._pending_key(session_id),
            pending.model_dump_json(),
            px=retention_ms,
        )
        return pending

    def pending_for(
        self,
        *,
        user_id: int,
        session_id: str,
    ) -> PendingMemoryChange | None:
        raw = self._client.get(self._pending_key(session_id))
        if not raw:
            return None
        pending = PendingMemoryChange.model_validate_json(raw)
        if pending.user_id != user_id or pending.session_id != session_id:
            return None
        if self._redis_now() >= pending.expires_at:
            return None
        return pending

    def confirm(self, *, user_id: int, session_id: str) -> MemoryChangeResult:
        pending_key = self._pending_key(session_id)
        while True:
            try:
                with self._client.pipeline() as pipe:
                    pipe.watch(pending_key)
                    raw = pipe.get(pending_key)
                    if not raw:
                        pipe.unwatch()
                        return self._result(False, "MEMORY_CHANGE_NOT_FOUND", "当前没有待确认的记忆变更", user_id)
                    pending = PendingMemoryChange.model_validate_json(raw)
                    if pending.user_id != user_id or pending.session_id != session_id:
                        pipe.unwatch()
                        return self._result(False, "MEMORY_CHANGE_NOT_FOUND", "当前没有待确认的记忆变更", user_id)
                    if self._redis_now() >= pending.expires_at:
                        pipe.multi()
                        pipe.delete(pending_key)
                        pipe.execute()
                        return self._result(False, "MEMORY_CHANGE_EXPIRED", "记忆变更确认已过期，请重新发起", user_id)

                    goal_key = self._goal_key(user_id)
                    preferences_key = self._preferences_key(user_id)
                    pipe.watch(goal_key, preferences_key)
                    goal_raw = pipe.get(goal_key)
                    preferences_raw = pipe.get(preferences_key)
                    now = self._redis_now()
                    goal, preferences = self._apply(
                        pending,
                        now,
                        goal_raw,
                        preferences_raw,
                    )

                    pipe.multi()
                    if goal is None:
                        pipe.delete(goal_key)
                    else:
                        pipe.set(goal_key, goal.model_dump_json(by_alias=True))
                    if preferences is None:
                        pipe.delete(preferences_key)
                    else:
                        pipe.set(
                            preferences_key,
                            preferences.model_dump_json(by_alias=True),
                        )
                    pipe.delete(pending_key)
                    pipe.execute()
                    return self._result(True, "MEMORY_CHANGE_APPLIED", "已按确认内容更新长期记忆", user_id)
            except redis.WatchError:
                continue

    def cancel_pending(self, *, user_id: int, session_id: str) -> int:
        key = self._pending_key(session_id)
        while True:
            try:
                with self._client.pipeline() as pipe:
                    pipe.watch(key)
                    raw = pipe.get(key)
                    if not raw:
                        pipe.unwatch()
                        return 0
                    pending = PendingMemoryChange.model_validate_json(raw)
                    if pending.user_id != user_id or pending.session_id != session_id:
                        pipe.unwatch()
                        return 0
                    pipe.multi()
                    pipe.delete(key)
                    pipe.execute()
                    return 1
            except redis.WatchError:
                continue

    def cancel_pending_by_session(self, session_id: str) -> int:
        return int(self._client.delete(self._pending_key(session_id)))

    def stats(self) -> dict[str, int]:
        return {
            "goals": sum(1 for _ in self._client.scan_iter(match=f"{self._prefix}:user:*:goal")),
            "preferences": sum(
                1 for _ in self._client.scan_iter(match=f"{self._prefix}:user:*:preferences")
            ),
            "pending": sum(1 for _ in self._client.scan_iter(match=f"{self._prefix}:pending:*")),
        }

    def clear(self) -> None:
        keys = list(self._client.scan_iter(match=f"{self._prefix}:*"))
        if keys:
            self._client.delete(*keys)

    def close(self) -> None:
        self._client.close()

    def _apply(
        self,
        pending: PendingMemoryChange,
        now: datetime,
        goal_raw: str | None,
        preferences_raw: str | None,
    ) -> tuple[RedemptionGoalData | None, UserPreferenceData | None]:
        goal = RedemptionGoalData.model_validate_json(goal_raw) if goal_raw else None
        preferences = (
            UserPreferenceData.model_validate_json(preferences_raw)
            if preferences_raw
            else None
        )
        if pending.change_type == MemoryChangeType.UPSERT_GOAL:
            target_date = date.fromisoformat(str(pending.payload["target_date"]))
            goal = RedemptionGoalData(
                userId=pending.user_id,
                targetAwardId=int(pending.payload["target_award_id"]),
                targetAwardName=str(pending.payload["target_award_name"]),
                targetDate=target_date,
                status="ACTIVE" if target_date >= business_date(now) else "EXPIRED",
                createdAt=goal.created_at if goal else now,
                updatedAt=now,
                sourceSession=pending.session_id,
            )
        elif pending.change_type == MemoryChangeType.REPLACE_PREFERENCES:
            preferences = UserPreferenceData(
                userId=pending.user_id,
                preferredCategories=pending.payload.get("preferred_categories", []),
                dislikedCategories=pending.payload.get("disliked_categories", []),
                taskPreferences=pending.payload.get("task_preferences", []),
                createdAt=preferences.created_at if preferences else now,
                updatedAt=now,
                sourceSession=pending.session_id,
            )
        elif pending.change_type == MemoryChangeType.FORGET_GOAL:
            goal = None
        elif pending.change_type == MemoryChangeType.FORGET_PREFERENCES:
            preferences = None
        elif pending.change_type == MemoryChangeType.FORGET_ALL:
            goal = None
            preferences = None
        return goal, preferences

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

    def _pending_key(self, session_id: str) -> str:
        return f"{self._prefix}:pending:{session_id}"
