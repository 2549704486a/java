from __future__ import annotations

import logging
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from langgraph.checkpoint.memory import InMemorySaver

from app.agent import build_agent, run_agent
from app.api_client import BusinessApiClient
from app.config import Settings
from app.skills.registry import SkillRegistry


logger = logging.getLogger(__name__)
AgentBuilder = Callable[[Settings, BusinessApiClient, int, SkillRegistry, Any], Any]
AgentRunner = Callable[[Any, str, str], str]


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
    ) -> tuple[str, float]:
        started = time.perf_counter()
        agent = self._agent_for(user_id)
        thread_id, slot = self._acquire_session(user_id, session_id)
        try:
            answer = self._agent_runner(agent, message, thread_id)
            return answer, (time.perf_counter() - started) * 1000
        finally:
            slot.lock.release()
            with self._lock:
                slot.in_use -= 1
                self._evict_sessions()

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
        }

    def close(self) -> None:
        with self._lock:
            self._agents.clear()
            self._sessions.clear()
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
        thread_id = f"user:{user_id}:session:{session_id}"
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
            logger.info("session_evicted thread_id=%s", evicted_thread_id)
