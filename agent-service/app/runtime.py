from __future__ import annotations

import json
import logging
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from langgraph.checkpoint.memory import InMemorySaver

from app.agent import append_agent_turn, build_agent, run_agent
from app.api_client import BusinessApiClient
from app.confirmation_store import ConfirmationStore, ConfirmationStoreBackend
from app.config import Settings
from app.models import PendingExchangeData, ToolEnvelope
from app.redis_confirmation_store import RedisConfirmationStore
from app.skills.controlled_exchange import (
    ControlledExchangeSkill,
    explicit_exchange_action,
)
from app.skills.registry import SkillRegistry
from app.trace import capture_tool_trace, execute_traced


logger = logging.getLogger(__name__)
AgentBuilder = Callable[
    [Settings, BusinessApiClient, int, SkillRegistry, Any, ConfirmationStoreBackend],
    Any,
]
AgentRunner = Callable[[Any, str, str, str | None], str]


@dataclass
class SessionSlot:
    lock: threading.Lock
    in_use: int = 0


class AgentRuntime:
    """管理服务级依赖，并按用户隔离、有限缓存 Agent 实例。"""

    def __init__(
        self,
        settings: Settings,
        client: BusinessApiClient | None = None,
        skill_registry: SkillRegistry | None = None,
        checkpointer: Any | None = None,
        agent_builder: AgentBuilder = build_agent,
        agent_runner: AgentRunner = run_agent,
        confirmation_store: ConfirmationStoreBackend | None = None,
    ) -> None:
        settings.require_llm_api_key()
        self.settings = settings
        self.client = client or BusinessApiClient(
            base_url=settings.business_api_base_url,
            timeout_seconds=settings.business_api_timeout_seconds,
            max_retries=settings.business_api_max_retries,
        )
        self._owns_client = client is None
        self.skill_registry = skill_registry or SkillRegistry()
        self.checkpointer = checkpointer or InMemorySaver()
        self.confirmation_store = confirmation_store or build_confirmation_store(
            settings
        )
        self._controlled_exchange = ControlledExchangeSkill(
            self.client,
            self.confirmation_store,
        )
        self._agent_builder = agent_builder
        self._agent_runner = agent_runner
        self._cache_size = max(1, settings.agent_cache_size)
        self._session_cache_size = max(1, settings.agent_session_cache_size)
        self._agents: OrderedDict[int, Any] = OrderedDict()
        self._sessions: OrderedDict[str, SessionSlot] = OrderedDict()
        self._lock = threading.Lock()

    def answer(
        self,
        user_id: int,
        session_id: str,
        message: str,
        request_id: str | None = None,
    ) -> tuple[str, float]:
        started = time.perf_counter()
        thread_id, slot = self._acquire_session(user_id, session_id)
        try:
            # 明确确认/取消属于高风险确定性动作。存在待确认记录时不再让模型猜测。
            action = explicit_exchange_action(message)
            pending = self.confirmation_store.pending_for(
                user_id=user_id,
                session_id=thread_id,
            )
            if action is not None and pending is not None:
                result = self._execute_exchange_action(
                    action=action,
                    user_id=user_id,
                    thread_id=thread_id,
                    request_id=request_id or thread_id,
                    confirmation_id=pending.confirmation_id,
                )
                # 确认/取消绕过模型执行，但结果仍需写回 LangGraph 记忆。
                # 否则下一轮模型看到的历史仍停留在“等待确认”。
                self._append_exchange_action_turn(
                    user_id=user_id,
                    thread_id=thread_id,
                    user_message=message,
                    assistant_message=result.message,
                )
                return result.message, (time.perf_counter() - started) * 1000

            agent = self._agent_for(user_id)
            # thread_id 隔离会话记忆；request_id 只串联本次请求的日志与轨迹。
            answer = self._agent_runner(agent, message, thread_id, request_id)
            return answer, (time.perf_counter() - started) * 1000
        finally:
            slot.lock.release()
            with self._lock:
                slot.in_use -= 1
                self._evict_sessions()

    def pending_exchange(
        self,
        user_id: int,
        session_id: str,
    ) -> PendingExchangeData | None:
        record = self.confirmation_store.pending_for(
            user_id=user_id,
            session_id=self._thread_id(user_id, session_id),
        )
        if record is None:
            return None
        return PendingExchangeData(
            status="AWAITING_CONFIRMATION",
            awardId=record.award_id,
            awardName=record.award_name,
            currentPoints=record.current_points,
            requiredPoints=record.required_points,
            remainingPoints=record.remaining_points,
            expiresAt=record.expires_at,
        )

    def health(self) -> dict[str, Any]:
        with self._lock:
            cached_agents = len(self._agents)
            cached_sessions = len(self._sessions)
        return {
            "status": "UP",
            "model": self.settings.llm_model,
            "cached_agents": cached_agents,
            "agent_cache_size": self._cache_size,
            "cached_sessions": cached_sessions,
            "session_cache_size": self._session_cache_size,
            "skills": self.skill_registry.trace_metadata(),
            "exchange_confirmations": self.confirmation_store.stats(),
        }

    def close(self) -> None:
        with self._lock:
            self._agents.clear()
            self._sessions.clear()
        # Redis Store 是多实例共享资源，停机只能关闭连接，不能清空业务状态。
        self.confirmation_store.close()
        if self._owns_client:
            self.client.close()

    def _agent_for(self, user_id: int) -> Any:
        with self._lock:
            cached = self._agents.pop(user_id, None)
            if cached is not None:
                self._agents[user_id] = cached
                logger.debug("agent_cache_hit user_id=%s", user_id)
                return cached

            agent = self._agent_builder(
                self.settings,
                self.client,
                user_id,
                self.skill_registry,
                self.checkpointer,
                self.confirmation_store,
            )
            self._agents[user_id] = agent
            logger.info("agent_cache_miss user_id=%s", user_id)
            if len(self._agents) > self._cache_size:
                evicted_user_id, _ = self._agents.popitem(last=False)
                logger.info("agent_cache_evicted user_id=%s", evicted_user_id)
            return agent

    def _acquire_session(
        self,
        user_id: int,
        session_id: str,
    ) -> tuple[str, SessionSlot]:
        thread_id = self._thread_id(user_id, session_id)
        with self._lock:
            slot = self._sessions.pop(thread_id, None)
            if slot is None:
                slot = SessionSlot(lock=threading.Lock())
                logger.info("session_created thread_id=%s", thread_id)
            self._sessions[thread_id] = slot
            slot.in_use += 1
            self._evict_sessions(excluded_thread_id=thread_id)
        slot.lock.acquire()
        return thread_id, slot

    def _execute_exchange_action(
        self,
        *,
        action: str,
        user_id: int,
        thread_id: str,
        request_id: str,
        confirmation_id: str,
    ) -> ToolEnvelope:
        tool_name = "confirm_exchange" if action == "CONFIRM" else "cancel_exchange"
        arguments = (
            {"confirmation_provided": True, "routing": "deterministic"}
            if action == "CONFIRM"
            else {"routing": "deterministic"}
        )
        with capture_tool_trace(request_id) as trace_session:
            try:
                if action == "CONFIRM":
                    result = execute_traced(
                        tool_name,
                        arguments,
                        lambda: self._controlled_exchange.confirm(
                            user_id=user_id,
                            session_id=thread_id,
                            request_id=request_id,
                            confirmation_id=confirmation_id,
                        ),
                    )
                else:
                    result = execute_traced(
                        tool_name,
                        arguments,
                        lambda: self._controlled_exchange.cancel(
                            user_id=user_id,
                            session_id=thread_id,
                        ),
                    )
            finally:
                logger.info(
                    "agent_tool_trace request_id=%s thread_id=%s events=%s",
                    request_id,
                    thread_id,
                    json.dumps(
                        trace_session.as_dicts(),
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                )
        logger.info(
            "exchange_action_routed request_id=%s thread_id=%s action=%s code=%s",
            request_id,
            thread_id,
            action,
            result.code,
        )
        return result

    def _append_exchange_action_turn(
        self,
        *,
        user_id: int,
        thread_id: str,
        user_message: str,
        assistant_message: str,
    ) -> None:
        try:
            append_agent_turn(
                self._agent_for(user_id),
                user_message,
                assistant_message,
                thread_id,
            )
        except Exception:
            # 兑换已经执行，记忆同步失败不能把成功响应改成接口异常。
            logger.exception(
                "exchange_history_sync_failed user_id=%s thread_id=%s",
                user_id,
                thread_id,
            )

    @staticmethod
    def _thread_id(user_id: int, session_id: str) -> str:
        return f"user:{user_id}:session:{session_id}"

    def _evict_sessions(self, excluded_thread_id: str | None = None) -> None:
        while len(self._sessions) > self._session_cache_size:
            evicted_thread_id = next(
                (
                    thread_id
                    for thread_id, slot in self._sessions.items()
                    if thread_id != excluded_thread_id and slot.in_use == 0
                ),
                None,
            )
            if evicted_thread_id is None:
                return
            self._sessions.pop(evicted_thread_id)
            self.checkpointer.delete_thread(evicted_thread_id)
            # 会话记忆淘汰时同步撤销待确认授权，避免孤立凭证继续可用。
            self.confirmation_store.cancel_pending_by_session(evicted_thread_id)
            logger.info("session_evicted thread_id=%s", evicted_thread_id)


def build_confirmation_store(settings: Settings) -> ConfirmationStoreBackend:
    backend = settings.exchange_confirmation_store
    if backend == "memory":
        return ConfirmationStore(
            ttl_seconds=settings.exchange_confirmation_ttl_seconds,
            capacity=settings.exchange_confirmation_capacity,
        )
    if backend == "redis":
        return RedisConfirmationStore.from_url(
            settings.exchange_confirmation_redis_url,
            ttl_seconds=settings.exchange_confirmation_ttl_seconds,
            capacity=settings.exchange_confirmation_capacity,
            retention_seconds=settings.exchange_confirmation_retention_seconds,
            key_prefix=settings.exchange_confirmation_redis_prefix,
        )
    raise ValueError(
        "EXCHANGE_CONFIRMATION_STORE 仅支持 memory 或 redis，"
        f"当前值为 {backend!r}"
    )
