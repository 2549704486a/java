from __future__ import annotations

import json
import logging
import threading
import time
from collections import OrderedDict
from typing import Any

from langchain.agents import create_agent
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import InMemorySaver

from app.agent import ensure_knowledge_citations, extract_message_text
from app.campaign_data import CampaignDataProvider
from app.config import Settings
from app.knowledge_search import KnowledgeSearchService
from app.operator_auth import AuthenticatedOperator
from app.operator_tools import build_operator_tools
from app.trace import capture_tool_trace


logger = logging.getLogger(__name__)
OPERATOR_KNOWLEDGE_TOOL_NAMES = frozenset({"search_operator_knowledge"})


def build_operator_system_prompt(knowledge_enabled: bool) -> str:
    knowledge_rule = (
        "涉及制度、预算口径、异常处理或历史案例时，先调用运营知识检索工具，并在回答中保留来源引用。"
        if knowledge_enabled
        else "运营知识检索当前不可用；涉及制度口径时必须明确说明无法核验，不得凭空补充。"
    )
    return f"""
你是积分激励系统的智能运营助手，帮助运营人员分析活动事实并生成可审阅的活动草案。

工作原则：
1. 实时客群、任务、奖品、库存和历史指标必须来自规划快照工具，不得猜测。
2. {knowledge_rule}
3. 生成活动草案前，必须具备客群、活动目标、现金预算、积分发放上限、起止时间等必要参数；缺失时先简洁追问。
4. 现金预算以分为工具参数单位，对用户回答时换算为元；积分发放上限是独立约束，不能与现金预算混为一谈。
5. 草案只用于人工审阅，不能声称已经发布、修改线上规则或触达用户。
6. 对高风险或不可执行请求明确说明边界，不伪造发布结果。
7. 回答使用简洁中文，先给结论，再列关键依据和下一步。
""".strip()


def build_operator_agent(
    settings: Settings,
    data_provider: CampaignDataProvider,
    operator: AuthenticatedOperator,
    knowledge_search: KnowledgeSearchService | None = None,
    checkpointer: Any | None = None,
):
    model = ChatOpenAI(
        model=settings.llm_model,
        api_key=settings.require_llm_api_key(),
        base_url=settings.llm_base_url,
        temperature=0,
        timeout=settings.llm_timeout_seconds,
        max_retries=1,
    )
    return create_agent(
        model=model,
        tools=build_operator_tools(
            data_provider=data_provider,
            operator=operator,
            knowledge_search=knowledge_search,
        ),
        system_prompt=build_operator_system_prompt(knowledge_search is not None),
        checkpointer=checkpointer,
    )


def run_operator_agent(
    agent,
    message: str,
    thread_id: str,
    request_id: str,
) -> str:
    with capture_tool_trace(request_id) as trace_session:
        try:
            result = agent.invoke(
                {"messages": [{"role": "user", "content": message}]},
                config={
                    "recursion_limit": 12,
                    "configurable": {"thread_id": thread_id},
                },
            )
        finally:
            logger.info(
                "operator_agent_tool_trace request_id=%s thread_id=%s events=%s",
                request_id,
                thread_id,
                json.dumps(
                    trace_session.as_dicts(),
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            )
    messages = result["messages"]
    response = extract_message_text(messages[-1].content)
    return ensure_knowledge_citations(
        messages,
        response,
        OPERATOR_KNOWLEDGE_TOOL_NAMES,
    )


class OperatorAgentRuntime:
    """缓存运营 Agent，并按运营身份与会话串行处理同一条对话。"""

    def __init__(
        self,
        settings: Settings,
        data_provider: CampaignDataProvider,
        knowledge_search: KnowledgeSearchService | None = None,
        checkpointer: Any | None = None,
    ) -> None:
        self._settings = settings
        self._data_provider = data_provider
        self._knowledge_search = knowledge_search
        self._checkpointer = checkpointer or InMemorySaver()
        self._agents: dict[str, Any] = {}
        self._session_locks: OrderedDict[str, threading.Lock] = OrderedDict()
        self._lock = threading.Lock()
        self._session_capacity = max(1, settings.agent_session_cache_size)

    def answer(
        self,
        operator: AuthenticatedOperator,
        session_id: str,
        message: str,
        request_id: str,
    ) -> tuple[str, float]:
        started = time.perf_counter()
        thread_id = f"operator:{operator.operator_id}:session:{session_id}"
        session_lock = self._acquire_session_lock(thread_id)
        try:
            answer = run_operator_agent(
                self._agent_for(operator),
                message,
                thread_id,
                request_id,
            )
        finally:
            session_lock.release()
        return answer, (time.perf_counter() - started) * 1000

    def close(self) -> None:
        with self._lock:
            self._agents.clear()
            self._session_locks.clear()

    def _agent_for(self, operator: AuthenticatedOperator):
        with self._lock:
            agent = self._agents.get(operator.operator_id)
            if agent is None:
                agent = build_operator_agent(
                    self._settings,
                    self._data_provider,
                    operator,
                    self._knowledge_search,
                    self._checkpointer,
                )
                self._agents[operator.operator_id] = agent
            return agent

    def _acquire_session_lock(self, thread_id: str) -> threading.Lock:
        with self._lock:
            lock = self._session_locks.pop(thread_id, None)
            if lock is None:
                lock = threading.Lock()
            self._session_locks[thread_id] = lock
            lock.acquire()
            while len(self._session_locks) > self._session_capacity:
                expired_thread_id = next(
                    (
                        candidate
                        for candidate, candidate_lock in self._session_locks.items()
                        if candidate != thread_id and not candidate_lock.locked()
                    ),
                    None,
                )
                if expired_thread_id is None:
                    break
                self._session_locks.pop(expired_thread_id)
                self._checkpointer.delete_thread(expired_thread_id)
            return lock
