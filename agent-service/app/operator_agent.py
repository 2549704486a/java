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
from app.api_client import BusinessApiClient
from app.campaign_data import CampaignDataProvider
from app.config import Settings
from app.knowledge_search import KnowledgeSearchService
from app.operator_auth import AuthenticatedOperator
from app.operator_intent import (
    OperatorIntent,
    OperatorIntentRouter,
)
from app.operator_tools import build_operator_tools
from app.trace import capture_tool_trace


logger = logging.getLogger(__name__)
OPERATOR_KNOWLEDGE_TOOL_NAMES = frozenset({"search_operator_knowledge"})


def build_operator_system_prompt(
    knowledge_enabled: bool,
    intent: OperatorIntent = OperatorIntent.KNOWLEDGE_QUERY,
) -> str:
    knowledge_rule = (
        "涉及制度、预算口径、活动执行、用户触达、异常处理或历史案例时，先调用运营知识检索工具，并在回答中保留来源引用。"
        if knowledge_enabled
        else "运营知识检索当前不可用；涉及制度口径时必须明确说明无法核验，不得凭空补充。"
    )
    intent_rule = {
        OperatorIntent.KNOWLEDGE_QUERY: (
            "当前请求是知识咨询。直接回答用户询问的方法、原理或流程；"
            "不得把能力边界声明当作答案。若当前项目尚未实现某项能力，"
            "先说明合理方案，再简短说明项目现状。"
        ),
        OperatorIntent.PLAN_REQUEST: (
            "当前请求是方案规划。围绕目标形成可审阅方案；只有生成正式活动草案时，"
            "才要求补齐草案所需业务参数并调用规划工具。"
        ),
        OperatorIntent.ACTION_REQUEST: (
            "当前请求明确要求执行业务动作。只能使用本轮提供的受控工具；"
            "没有对应工具时说明当前不能执行，并给出人工工作台中的最近可行步骤。"
        ),
    }[intent]
    return f"""
你是积分激励系统的智能运营助手，帮助运营人员分析活动事实并生成可审阅的活动草案。

工作原则：
1. {intent_rule}
2. 实时客群、任务、奖品、库存和历史指标必须来自规划快照工具，不得猜测。
3. {knowledge_rule}
4. 生成活动草案前，必须具备客群、活动目标、现金预算、积分发放上限、起止时间等必要参数；缺失时先简洁追问。
5. 现金预算以分为工具参数单位，对用户回答时换算为元；积分发放上限是独立约束，不能与现金预算混为一谈。
6. Agent 只负责生成和保存草案；运营人员可以在工作台提交、审核和发布，发布由确定性服务执行。发布活动记录不等于已经向用户发送通知。
7. 不能声称已经修改线上规则或触达用户，也不能伪造执行结果。
8. 回答使用简洁中文，先回答用户真正关心的问题，再列关键依据和下一步。
""".strip()


def select_operator_tools(tools: list[Any], intent: OperatorIntent) -> list[Any]:
    """按当前意图收敛 Tool；分类结果只是路由依据，不构成业务授权。"""

    allowed_names = {
        OperatorIntent.KNOWLEDGE_QUERY: {
            "get_campaign_planning_snapshot",
            "search_operator_knowledge",
        },
        OperatorIntent.PLAN_REQUEST: {
            "get_campaign_planning_snapshot",
            "search_operator_knowledge",
            "draft_campaign_plan",
        },
        OperatorIntent.ACTION_REQUEST: {"search_operator_knowledge"},
    }[intent]
    return [tool for tool in tools if tool.name in allowed_names]


def build_operator_agent(
    settings: Settings,
    data_provider: CampaignDataProvider,
    operator: AuthenticatedOperator,
    business_client: BusinessApiClient,
    knowledge_search: KnowledgeSearchService | None = None,
    checkpointer: Any | None = None,
    intent: OperatorIntent = OperatorIntent.KNOWLEDGE_QUERY,
):
    model = ChatOpenAI(
        model=settings.llm_model,
        api_key=settings.require_llm_api_key(),
        base_url=settings.llm_base_url,
        temperature=0,
        timeout=settings.llm_timeout_seconds,
        max_retries=1,
    )
    tools = build_operator_tools(
        data_provider=data_provider,
        operator=operator,
        knowledge_search=knowledge_search,
        business_client=business_client,
    )
    return create_agent(
        model=model,
        tools=select_operator_tools(tools, intent),
        system_prompt=build_operator_system_prompt(
            knowledge_search is not None,
            intent,
        ),
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
        business_client: BusinessApiClient,
        knowledge_search: KnowledgeSearchService | None = None,
        checkpointer: Any | None = None,
        intent_router: OperatorIntentRouter | None = None,
    ) -> None:
        self._settings = settings
        self._data_provider = data_provider
        self._business_client = business_client
        self._knowledge_search = knowledge_search
        self._checkpointer = checkpointer or InMemorySaver()
        self._intent_router = intent_router or OperatorIntentRouter.from_settings(
            settings
        )
        self._agents: dict[tuple[str, OperatorIntent], Any] = {}
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
            decision = self._intent_router.classify(message, request_id)
            answer = run_operator_agent(
                self._agent_for(operator, decision.intent),
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

    def _agent_for(
        self,
        operator: AuthenticatedOperator,
        intent: OperatorIntent,
    ):
        with self._lock:
            cache_key = (operator.operator_id, intent)
            agent = self._agents.get(cache_key)
            if agent is None:
                agent = build_operator_agent(
                    self._settings,
                    self._data_provider,
                    operator,
                    self._business_client,
                    self._knowledge_search,
                    self._checkpointer,
                    intent,
                )
                self._agents[cache_key] = agent
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
