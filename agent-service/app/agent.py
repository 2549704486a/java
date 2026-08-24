from __future__ import annotations

import json
import logging

from langchain.agents import create_agent
from langchain_core.messages import AIMessage, HumanMessage
from langchain_openai import ChatOpenAI

from app.api_client import BusinessApiClient
from app.confirmation_store import ConfirmationStoreBackend
from app.config import Settings
from app.context_window import ContextWindowPolicy, build_context_window_middleware
from app.execution_context import bind_execution_context
from app.growth_memory_store import GrowthMemoryStoreBackend
from app.knowledge_search import KnowledgeSearchService
from app.prompt import build_system_prompt
from app.skills.registry import SkillRegistry
from app.tools import build_tools
from app.trace import capture_tool_trace


logger = logging.getLogger(__name__)


def extract_message_text(content) -> str:
    """兼容模型返回的纯文本和分块文本。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        text_parts = [
            part.get("text", "")
            for part in content
            if isinstance(part, dict) and part.get("type") == "text"
        ]
        return "\n".join(part for part in text_parts if part)
    return str(content)


def _as_tool_payload(value) -> dict | None:
    if isinstance(value, dict):
        if value.get("type") == "text" and isinstance(value.get("text"), str):
            return _as_tool_payload(value["text"])
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (TypeError, json.JSONDecodeError):
            return None
        return parsed if isinstance(parsed, dict) else None
    if isinstance(value, list):
        for item in value:
            payload = _as_tool_payload(item)
            if payload is not None:
                return payload
    return None


def collect_knowledge_citations(
    messages,
    tool_names: frozenset[str] = frozenset({"search_business_knowledge"}),
) -> list[str]:
    """从给定消息范围内的知识检索 Tool 返回值提取用户可读引用。"""
    citations: list[str] = []
    for message in messages:
        if (
            getattr(message, "type", None) != "tool"
            or getattr(message, "name", None) not in tool_names
        ):
            continue
        payload = _as_tool_payload(getattr(message, "artifact", None))
        if payload is None:
            payload = _as_tool_payload(getattr(message, "content", None))
        data = payload.get("data") if payload else None
        matches = data.get("matches", []) if isinstance(data, dict) else []
        for match in matches:
            citation = match.get("citation") if isinstance(match, dict) else None
            if citation and citation not in citations:
                citations.append(citation)
    return citations


def latest_conversation_turn(messages) -> list:
    """截取最后一条用户消息开始的当前轮，避免历史 Tool 结果污染引用。"""

    for index in range(len(messages) - 1, -1, -1):
        if isinstance(messages[index], HumanMessage):
            return list(messages[index:])
    # 单元测试或无状态调用可能只返回 ToolMessage 和 AIMessage。
    return list(messages)


def ensure_knowledge_citations(
    messages,
    response: str,
    tool_names: frozenset[str] = frozenset({"search_business_knowledge"}),
) -> str:
    """规范化真实 Tool 引用，并在模型完全漏引时补充最相关来源。"""
    current_turn_messages = latest_conversation_turn(messages)
    citations = collect_knowledge_citations(current_turn_messages, tool_names)
    historical_citations = collect_knowledge_citations(messages, tool_names)
    stale_citations = [
        citation for citation in historical_citations if citation not in citations
    ]

    normalized = response
    for citation in stale_citations:
        normalized = normalized.replace(citation, "")
    if stale_citations:
        normalized_lines = [
            line
            for line in normalized.splitlines()
            if line.strip() not in {"检索来源：", "检索来源:"}
        ]
        normalized = "\n".join(normalized_lines).rstrip()
    if not citations:
        return normalized

    for citation in citations:
        first = normalized.find(citation)
        if first < 0:
            continue
        boundary = first + len(citation)
        normalized = normalized[:boundary] + normalized[boundary:].replace(
            citation,
            "",
        )
    if any(citation in normalized for citation in citations):
        return normalized
    return f"{normalized.rstrip()}\n\n检索来源：{citations[0]}"


def build_agent(
    settings: Settings,
    client: BusinessApiClient,
    user_id: int,
    skill_registry: SkillRegistry | None = None,
    checkpointer=None,
    confirmation_store: ConfirmationStoreBackend | None = None,
    knowledge_search: KnowledgeSearchService | None = None,
    growth_memory_store: GrowthMemoryStoreBackend | None = None,
):
    registry = skill_registry or SkillRegistry()
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
        tools=build_tools(
            client=client,
            user_id=user_id,
            skill_registry=registry,
            confirmation_store=confirmation_store,
            knowledge_search=knowledge_search,
            growth_memory_store=growth_memory_store,
        ),
        system_prompt=build_system_prompt(knowledge_search is not None),
        middleware=[
            build_context_window_middleware(
                policy=ContextWindowPolicy(
                    max_tokens=settings.agent_context_max_tokens,
                    max_turns=settings.agent_context_max_turns,
                ),
                user_id=user_id,
                confirmation_store=confirmation_store,
            )
        ],
        checkpointer=checkpointer,
    )


def run_agent(
    agent,
    message: str,
    thread_id: str | None = None,
    request_id: str | None = None,
) -> str:
    config = {"recursion_limit": 12}
    if thread_id is not None:
        config["configurable"] = {"thread_id": thread_id}
    correlation_id = request_id or thread_id or "cli"
    # 一次 Agent 请求对应一个轨迹会话，期间执行的 Tool/Skill 会自动写入该会话。
    with capture_tool_trace(correlation_id) as trace_session, bind_execution_context(
        thread_id
    ):
        try:
            result = agent.invoke(
                {"messages": [{"role": "user", "content": message}]},
                config=config,
            )
        finally:
            # 即使模型或工具抛出异常，也保留已经发生的调用，便于还原失败现场。
            logger.info(
                "agent_tool_trace request_id=%s thread_id=%s events=%s",
                request_id or "-",
                thread_id or "-",
                json.dumps(
                    trace_session.as_dicts(),
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            )
    messages = result["messages"]
    response = extract_message_text(messages[-1].content)
    return ensure_knowledge_citations(messages, response)


def append_agent_turn(
    agent,
    user_message: str,
    assistant_message: str,
    thread_id: str,
) -> None:
    """将确定性路由产生的对话写回 Agent 记忆，但不再次调用模型。"""
    agent.update_state(
        {"configurable": {"thread_id": thread_id}},
        {
            "messages": [
                HumanMessage(content=user_message),
                AIMessage(content=assistant_message),
            ]
        },
    )
