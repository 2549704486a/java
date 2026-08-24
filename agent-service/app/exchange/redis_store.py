from __future__ import annotations

import hashlib
import secrets
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

import redis

from app.exchange.confirmation_store import (
    ClaimResult,
    ConfirmationRecord,
    ConfirmationStatus,
)


_CREATE_SCRIPT = r"""
if redis.call('EXISTS', KEYS[1]) == 1 then
    return 'TOKEN_EXISTS'
end

local capacity = tonumber(ARGV[16])
if redis.call('ZCARD', KEYS[3]) >= capacity then
    local members = redis.call('ZRANGE', KEYS[3], 0, -1)
    for _, member in ipairs(members) do
        if redis.call('EXISTS', ARGV[17] .. member) == 0 then
            redis.call('ZREM', KEYS[3], member)
        end
    end
end

while redis.call('ZCARD', KEYS[3]) >= capacity do
    local members = redis.call('ZRANGE', KEYS[3], 0, -1)
    local removed = false
    for _, member in ipairs(members) do
        local old_key = ARGV[17] .. member
        local old_status = redis.call('HGET', old_key, 'status')
        if old_status ~= 'EXECUTING' then
            redis.call('DEL', old_key)
            redis.call('ZREM', KEYS[3], member)
            removed = true
            break
        end
    end
    if not removed then
        return 'CAPACITY_FULL'
    end
end

local previous = redis.call('GET', KEYS[2])
if previous then
    local previous_key = ARGV[17] .. previous
    if redis.call('HGET', previous_key, 'status') == 'PREPARED' then
        redis.call('HSET', previous_key, 'status', 'CANCELLED')
        redis.call('PEXPIRE', previous_key, ARGV[15])
    end
end

redis.call(
    'HSET', KEYS[1],
    'confirmation_id', ARGV[1],
    'user_id', ARGV[2],
    'session_id', ARGV[3],
    'award_id', ARGV[4],
    'award_name', ARGV[5],
    'current_points', ARGV[6],
    'required_points', ARGV[7],
    'remaining_points', ARGV[8],
    'request_id', ARGV[9],
    'status', ARGV[10],
    'created_at', ARGV[12],
    'expires_at', ARGV[13],
    'result_code', ''
)
redis.call('PEXPIRE', KEYS[1], ARGV[15])
redis.call('SET', KEYS[2], ARGV[1], 'PX', ARGV[14])
redis.call('ZADD', KEYS[3], ARGV[11], ARGV[1])
return 'CREATED'
"""


_CLAIM_SCRIPT = r"""
if redis.call('EXISTS', KEYS[1]) == 0 then
    return 'CONFIRMATION_NOT_FOUND'
end
if redis.call('HGET', KEYS[1], 'user_id') ~= ARGV[1]
    or redis.call('HGET', KEYS[1], 'session_id') ~= ARGV[2] then
    return 'CONFIRMATION_NOT_FOUND'
end

local status = redis.call('HGET', KEYS[1], 'status')
local expires_at = tonumber(redis.call('HGET', KEYS[1], 'expires_at'))
if status == 'PREPARED' and tonumber(ARGV[4]) >= expires_at then
    redis.call('HSET', KEYS[1], 'status', 'EXPIRED')
    redis.call('PEXPIRE', KEYS[1], ARGV[5])
    if redis.call('GET', KEYS[2]) == ARGV[6] then
        redis.call('DEL', KEYS[2])
    end
    return 'CONFIRMATION_EXPIRED'
end
if status == 'EXPIRED' then
    return 'CONFIRMATION_EXPIRED'
end
if status ~= 'PREPARED' then
    return 'CONFIRMATION_ALREADY_USED'
end
if redis.call('HGET', KEYS[1], 'request_id') == ARGV[3] then
    return 'CONFIRMATION_REQUIRES_NEW_TURN'
end

redis.call('HSET', KEYS[1], 'status', 'EXECUTING')
redis.call('PEXPIRE', KEYS[1], ARGV[5])
if redis.call('GET', KEYS[2]) == ARGV[6] then
    redis.call('DEL', KEYS[2])
end
return 'CONFIRMATION_CLAIMED'
"""


_FINISH_SCRIPT = r"""
if redis.call('HGET', KEYS[1], 'status') ~= 'EXECUTING' then
    return 0
end
redis.call('HSET', KEYS[1], 'status', ARGV[1], 'result_code', ARGV[2])
redis.call('PEXPIRE', KEYS[1], ARGV[3])
return 1
"""


_CANCEL_SCRIPT = r"""
local confirmation_id = redis.call('GET', KEYS[1])
if not confirmation_id then
    return 0
end
local record_key = ARGV[3] .. confirmation_id
if redis.call('EXISTS', record_key) == 0 then
    redis.call('DEL', KEYS[1])
    return 0
end
if redis.call('HGET', record_key, 'session_id') ~= ARGV[2] then
    return 0
end
if ARGV[1] ~= '' and redis.call('HGET', record_key, 'user_id') ~= ARGV[1] then
    return 0
end
if redis.call('HGET', record_key, 'status') ~= 'PREPARED' then
    redis.call('DEL', KEYS[1])
    return 0
end
redis.call('HSET', record_key, 'status', 'CANCELLED')
redis.call('PEXPIRE', record_key, ARGV[4])
redis.call('DEL', KEYS[1])
return 1
"""


_PENDING_SCRIPT = r"""
local confirmation_id = redis.call('GET', KEYS[1])
if not confirmation_id then
    return 'NONE'
end
local record_key = ARGV[4] .. confirmation_id
if redis.call('EXISTS', record_key) == 0 then
    redis.call('DEL', KEYS[1])
    return 'NONE'
end
if redis.call('HGET', record_key, 'user_id') ~= ARGV[1]
    or redis.call('HGET', record_key, 'session_id') ~= ARGV[2] then
    return 'NONE'
end
if redis.call('HGET', record_key, 'status') ~= 'PREPARED' then
    redis.call('DEL', KEYS[1])
    return 'NONE'
end
if tonumber(ARGV[3]) >= tonumber(redis.call('HGET', record_key, 'expires_at')) then
    redis.call('HSET', record_key, 'status', 'EXPIRED')
    redis.call('PEXPIRE', record_key, ARGV[5])
    redis.call('DEL', KEYS[1])
    return 'NONE'
end
return confirmation_id
"""


class RedisConfirmationStore:
    """使用 Redis 共享确认状态，并用 Lua 保证跨实例状态迁移的原子性。"""

    def __init__(
        self,
        client: redis.Redis,
        *,
        ttl_seconds: int = 120,
        capacity: int = 10_000,
        retention_seconds: int = 3600,
        key_prefix: str = "agent:exchange:confirmation",
        token_factory: Callable[[], str] | None = None,
    ) -> None:
        self._client = client
        self._ttl = timedelta(seconds=max(1, ttl_seconds))
        self._capacity = max(1, capacity)
        # 记录必须比待确认 TTL 活得更久，才能准确返回“已过期/已使用”。
        self._retention_seconds = max(
            retention_seconds,
            int(self._ttl.total_seconds()) + 60,
        )
        self._prefix = key_prefix.strip().rstrip(":")
        if not self._prefix:
            raise ValueError("Redis 确认凭证 key prefix 不能为空")
        self._record_prefix = f"{self._prefix}:record:"
        self._index_key = f"{self._prefix}:records"
        self._token_factory = token_factory or (lambda: secrets.token_urlsafe(32))

    @classmethod
    def from_url(
        cls,
        url: str,
        **kwargs,
    ) -> RedisConfirmationStore:
        client = redis.Redis.from_url(
            url,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
            health_check_interval=30,
        )
        client.ping()
        return cls(client, **kwargs)

    def create(
        self,
        *,
        user_id: int,
        session_id: str,
        award_id: int,
        award_name: str,
        current_points: int,
        required_points: int,
        request_id: str,
    ) -> ConfirmationRecord:
        now = self._redis_now()
        expires_at = now + self._ttl
        pending_key = self._pending_key(session_id)
        for _ in range(10):
            confirmation_id = self._token_factory()
            if not confirmation_id:
                continue
            result = self._client.eval(
                _CREATE_SCRIPT,
                3,
                self._record_key(confirmation_id),
                pending_key,
                self._index_key,
                confirmation_id,
                str(user_id),
                session_id,
                str(award_id),
                award_name,
                str(current_points),
                str(required_points),
                str(current_points - required_points),
                request_id,
                ConfirmationStatus.PREPARED.value,
                str(int(now.timestamp() * 1000)),
                self._timestamp(now),
                self._timestamp(expires_at),
                str(int(self._ttl.total_seconds() * 1000)),
                str(self._retention_seconds * 1000),
                str(self._capacity),
                self._record_prefix,
            )
            if result == "CAPACITY_FULL":
                raise RuntimeError("确认存储容量已满，请稍后再试")
            if result == "CREATED":
                record = self.snapshot(confirmation_id)
                if record is None:
                    raise RuntimeError("确认凭证创建后无法读取")
                return record
        raise RuntimeError("无法生成唯一兑换确认凭证")

    def claim(
        self,
        confirmation_id: str,
        *,
        user_id: int,
        session_id: str,
        request_id: str,
    ) -> ClaimResult:
        code = self._client.eval(
            _CLAIM_SCRIPT,
            2,
            self._record_key(confirmation_id),
            self._pending_key(session_id),
            str(user_id),
            session_id,
            request_id,
            self._timestamp(self._redis_now()),
            str(self._retention_seconds * 1000),
            confirmation_id,
        )
        if code != "CONFIRMATION_CLAIMED":
            return ClaimResult(str(code))
        record = self.snapshot(confirmation_id)
        if record is None:
            return ClaimResult("CONFIRMATION_NOT_FOUND")
        return ClaimResult("CONFIRMATION_CLAIMED", record)

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
        updated = self._client.eval(
            _FINISH_SCRIPT,
            1,
            self._record_key(confirmation_id),
            status.value,
            result_code,
            str(self._retention_seconds * 1000),
        )
        return self.snapshot(confirmation_id) if int(updated) == 1 else None

    def cancel_pending(self, *, user_id: int, session_id: str) -> int:
        return self._cancel_pending(str(user_id), session_id)

    def cancel_pending_by_session(self, session_id: str) -> int:
        return self._cancel_pending("", session_id)

    def snapshot(self, confirmation_id: str) -> ConfirmationRecord | None:
        values = self._client.hgetall(self._record_key(confirmation_id))
        return self._record_from_hash(values) if values else None

    def pending_for(
        self,
        *,
        user_id: int,
        session_id: str,
    ) -> ConfirmationRecord | None:
        confirmation_id = self._client.eval(
            _PENDING_SCRIPT,
            1,
            self._pending_key(session_id),
            str(user_id),
            session_id,
            self._timestamp(self._redis_now()),
            self._record_prefix,
            str(self._retention_seconds * 1000),
        )
        if confirmation_id == "NONE":
            return None
        return self.snapshot(str(confirmation_id))

    def stats(self) -> dict[str, int]:
        records = [
            self._record_from_hash(values)
            for key in self._client.scan_iter(match=f"{self._record_prefix}*")
            if (values := self._client.hgetall(key))
        ]
        now = self._redis_now()
        return {
            "total": len(records),
            "pending": sum(
                record.status == ConfirmationStatus.PREPARED
                and now < record.expires_at
                for record in records
            ),
            "executing": sum(
                record.status == ConfirmationStatus.EXECUTING for record in records
            ),
        }

    def clear(self) -> None:
        """仅供测试和显式运维清理；Agent 正常停机不会调用它。"""
        keys = list(self._client.scan_iter(match=f"{self._prefix}:*"))
        if keys:
            self._client.delete(*keys)

    def close(self) -> None:
        self._client.close()

    def _cancel_pending(self, user_id: str, session_id: str) -> int:
        return int(
            self._client.eval(
                _CANCEL_SCRIPT,
                1,
                self._pending_key(session_id),
                user_id,
                session_id,
                self._record_prefix,
                str(self._retention_seconds * 1000),
            )
        )

    def _redis_now(self) -> datetime:
        seconds, microseconds = self._client.time()
        return datetime.fromtimestamp(
            float(seconds) + float(microseconds) / 1_000_000,
            tz=timezone.utc,
        )

    def _record_key(self, confirmation_id: str) -> str:
        return f"{self._record_prefix}{confirmation_id}"

    def _pending_key(self, session_id: str) -> str:
        session_hash = hashlib.sha256(session_id.encode("utf-8")).hexdigest()
        return f"{self._prefix}:pending:{session_hash}"

    @staticmethod
    def _timestamp(value: datetime) -> str:
        return f"{value.timestamp():.6f}"

    @staticmethod
    def _record_from_hash(values: dict[str, str]) -> ConfirmationRecord:
        return ConfirmationRecord(
            confirmation_id=values["confirmation_id"],
            user_id=int(values["user_id"]),
            session_id=values["session_id"],
            award_id=int(values["award_id"]),
            award_name=values["award_name"],
            current_points=int(values["current_points"]),
            required_points=int(values["required_points"]),
            remaining_points=int(values["remaining_points"]),
            request_id=values["request_id"],
            status=ConfirmationStatus(values["status"]),
            created_at=datetime.fromtimestamp(
                float(values["created_at"]), tz=timezone.utc
            ),
            expires_at=datetime.fromtimestamp(
                float(values["expires_at"]), tz=timezone.utc
            ),
            result_code=values.get("result_code") or None,
        )
