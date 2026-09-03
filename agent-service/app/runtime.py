from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from langgraph.checkpoint.memory import InMemorySaver

from app.agent import append_agent_turn, build_agent, run_agent
from app.api_client import BusinessApiClient
from app.exchange.confirmation_store import ConfirmationStore, ConfirmationStoreBackend
from app.memory.store import GrowthMemoryStore, GrowthMemoryStoreBackend
from app.config import Settings
from app.knowledge.search import KnowledgeSearchService, open_knowledge_search
from app.mcp_award_tool import (
    McpAwardToolBinding,
    discover_award_detail_mcp_tool,
)
from app.models import PendingExchangeData, ToolEnvelope
from app.memory.mysql_store import MysqlGrowthMemoryStore
from app.exchange.redis_store import RedisConfirmationStore
from app.memory.redis_store import RedisGrowthMemoryStore
from app.observability.collector import record_current_tool_traces
from app.services.controlled_exchange import (
    ControlledExchangeService,
    explicit_exchange_action,
)
from app.skills.registry import SkillRegistry
from app.trace import capture_tool_trace, execute_traced


logger = logging.getLogger(__name__)
AgentBuilder = Callable[..., Any]
AgentRunner = Callable[[Any, str, str, str | None], Awaitable[str]]


@dataclass
class SessionSlot:
    lock: asyncio.Lock
    in_use: int = 0
    last_access_monotonic: float = 0.0


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
        knowledge_search: KnowledgeSearchService | None = None,
        operator_knowledge_search: KnowledgeSearchService | None = None,
        growth_memory_store: GrowthMemoryStoreBackend | None = None,
        clock: Callable[[], float] = time.monotonic,
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
        self.growth_memory_store = growth_memory_store or build_growth_memory_store(
            settings
        )
        self.knowledge_search = knowledge_search
        self._owns_knowledge_search = False
        if self.knowledge_search is None and settings.rag_enabled:
            self.knowledge_search = open_knowledge_search(settings)
            self._owns_knowledge_search = True
        self.operator_knowledge_search = operator_knowledge_search
        self._owns_operator_knowledge_search = False
        if self.operator_knowledge_search is None and settings.rag_enabled:
            self.operator_knowledge_search = open_knowledge_search(
                settings,
                allowed_audiences=("operator",),
            )
            self._owns_operator_knowledge_search = True
        self._controlled_exchange = ControlledExchangeService(
            self.client,
            self.confirmation_store,
        )
        self._agent_builder = agent_builder
        self._agent_runner = agent_runner
        self._cache_size = max(1, settings.agent_cache_size)
        self._session_cache_size = max(1, settings.agent_session_cache_size)
        self._session_ttl_seconds = max(1, settings.agent_session_ttl_seconds)
        self._clock = clock
        self._agents: OrderedDict[int, Any] = OrderedDict()
        self._sessions: OrderedDict[str, SessionSlot] = OrderedDict()
        self._lock = threading.Lock()
        self._mcp_award_binding: McpAwardToolBinding | None = None

    async def initialize(self) -> None:
        """在服务 ready 前完成可选 MCP Tool 的发现与契约校验。"""
        if self.settings.award_detail_transport == "rest":
            return
        if self._mcp_award_binding is not None:
            return
        self._mcp_award_binding = await discover_award_detail_mcp_tool(self.settings)
        logger.info(
            "mcp_award_tool_ready server=%s discovered_tool_count=%s",
            self._mcp_award_binding.server_name,
            self._mcp_award_binding.discovered_tool_count,
        )

    async def answer(
        self,
        user_id: int,
        session_id: str,
        message: str,
        request_id: str | None = None,
    ) -> tuple[str, float]:
        started = time.perf_counter()
        thread_id, slot = await self._acquire_session(user_id, session_id)
        try:
            # 明确确认/取消属于高风险确定性动作。存在待确认记录时不再让模型猜测。
            action = explicit_exchange_action(message)
            pending = await asyncio.to_thread(
                self.confirmation_store.pending_for,
                user_id=user_id,
                session_id=thread_id,
            )
            if action is not None and pending is not None:
                result = await asyncio.to_thread(
                    self._execute_exchange_action,
                    action=action,
                    user_id=user_id,
                    thread_id=thread_id,
                    request_id=request_id or thread_id,
                    confirmation_id=pending.confirmation_id,
                )
                # 确认/取消绕过模型执行，但结果仍需写回 LangGraph 记忆。
                # 否则下一轮模型看到的历史仍停留在“等待确认”。
                await self._append_exchange_action_turn(
                    user_id=user_id,
                    thread_id=thread_id,
                    user_message=message,
                    assistant_message=result.message,
                )
                return result.message, (time.perf_counter() - started) * 1000

            agent = self._agent_for(user_id)
            # thread_id 隔离会话记忆；request_id 只串联本次请求的日志与轨迹。
            answer = await self._agent_runner(agent, message, thread_id, request_id)
            return answer, (time.perf_counter() - started) * 1000
        finally:
            slot.lock.release()
            with self._lock:
                slot.in_use -= 1
                slot.last_access_monotonic = self._clock()
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
            "session_ttl_seconds": self._session_ttl_seconds,
            "context_max_tokens": self.settings.agent_context_max_tokens,
            "context_max_turns": self.settings.agent_context_max_turns,
            "skills": self.skill_registry.trace_metadata(),
            "exchange_confirmations": self.confirmation_store.stats(),
            "growth_memory": self.growth_memory_store.stats(),
            "rag_enabled": self.knowledge_search is not None,
            "operator_rag_enabled": self.operator_knowledge_search is not None,
            "award_detail_transport": self.settings.award_detail_transport,
            "mcp_award_tool_ready": self._mcp_award_binding is not None,
        }

    def close(self) -> None:
        with self._lock:
            self._agents.clear()
            self._sessions.clear()
        # Redis Store 是多实例共享资源，停机只能关闭连接，不能清空业务状态。
        self.confirmation_store.close()
        self.growth_memory_store.close()
        if self._owns_knowledge_search and self.knowledge_search is not None:
            self.knowledge_search.close()
        if (
            self._owns_operator_knowledge_search
            and self.operator_knowledge_search is not None
        ):
            self.operator_knowledge_search.close()
        if self._owns_client:
            self.client.close()

    def _agent_for(self, user_id: int) -> Any:
        if (
            self.settings.award_detail_transport == "mcp"
            and self._mcp_award_binding is None
        ):
            raise RuntimeError("MCP 奖品 Tool 尚未初始化，不能创建用户 Agent")
        with self._lock:
            cached = self._agents.pop(user_id, None)
            if cached is not None:
                self._agents[user_id] = cached
                logger.debug("agent_cache_hit user_id=%s", user_id)
                return cached

            builder_arguments = (
                self.settings,
                self.client,
                user_id,
                self.skill_registry,
                self.checkpointer,
                self.confirmation_store,
                self.knowledge_search,
                self.growth_memory_store,
            )
            if self._mcp_award_binding is None:
                agent = self._agent_builder(*builder_arguments)
            else:
                agent = self._agent_builder(
                    *builder_arguments,
                    award_detail_tool=self._mcp_award_binding.tool,
                )
            self._agents[user_id] = agent
            logger.info("agent_cache_miss user_id=%s", user_id)
            if len(self._agents) > self._cache_size:
                evicted_user_id, _ = self._agents.popitem(last=False)
                logger.info("agent_cache_evicted user_id=%s", evicted_user_id)
            return agent

    async def _acquire_session(
        self,
        user_id: int,
        session_id: str,
    ) -> tuple[str, SessionSlot]:
        thread_id = self._thread_id(user_id, session_id)
        with self._lock:
            now = self._clock()
            self._evict_sessions(now=now)
            slot = self._sessions.pop(thread_id, None)
            if slot is None:
                slot = SessionSlot(
                    lock=asyncio.Lock(),
                    last_access_monotonic=now,
                )
                logger.info("session_created thread_id=%s", thread_id)
            self._sessions[thread_id] = slot
            slot.in_use += 1
            self._evict_sessions(excluded_thread_id=thread_id)
        try:
            await slot.lock.acquire()
        except BaseException:
            # 等锁期间被取消也要归还引用计数，否则该会话将永远无法淘汰。
            with self._lock:
                slot.in_use -= 1
                slot.last_access_monotonic = self._clock()
                self._evict_sessions()
            raise
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
                record_current_tool_traces(trace_session.snapshot())
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

    async def _append_exchange_action_turn(
        self,
        *,
        user_id: int,
        thread_id: str,
        user_message: str,
        assistant_message: str,
    ) -> None:
        try:
            await append_agent_turn(
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

    def _evict_sessions(
        self,
        excluded_thread_id: str | None = None,
        now: float | None = None,
    ) -> None:
        current = self._clock() if now is None else now
        expired_thread_ids = [
            thread_id
            for thread_id, slot in self._sessions.items()
            if thread_id != excluded_thread_id
            and slot.in_use == 0
            and current - slot.last_access_monotonic >= self._session_ttl_seconds
        ]
        for thread_id in expired_thread_ids:
            self._remove_session(thread_id, reason="expired")

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
            self._remove_session(evicted_thread_id, reason="capacity")

    def _remove_session(self, thread_id: str, *, reason: str) -> None:
        self._sessions.pop(thread_id, None)
        self.checkpointer.delete_thread(thread_id)
        # 会话记忆淘汰时同步撤销待确认授权，避免孤立凭证继续可用。
        self.confirmation_store.cancel_pending_by_session(thread_id)
        logger.info("session_evicted thread_id=%s reason=%s", thread_id, reason)


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


def build_growth_memory_store(settings: Settings) -> GrowthMemoryStoreBackend:
    backend = settings.growth_memory_store
    if backend == "memory":
        return GrowthMemoryStore()
    if backend == "redis":
        return RedisGrowthMemoryStore.from_url(
            settings.growth_memory_redis_url,
            key_prefix=settings.growth_memory_redis_prefix,
        )
    if backend == "mysql":
        return MysqlGrowthMemoryStore(
            host=settings.growth_memory_mysql_host,
            port=settings.growth_memory_mysql_port,
            database=settings.growth_memory_mysql_database,
            user=settings.growth_memory_mysql_user,
            password=settings.growth_memory_mysql_password,
            table_name=settings.growth_memory_mysql_table,
            connect_timeout=settings.growth_memory_mysql_connect_timeout,
        )
    raise ValueError(
        "GROWTH_MEMORY_STORE 仅支持 memory 或 redis，"
        f"当前值为 {backend!r}"
    )
