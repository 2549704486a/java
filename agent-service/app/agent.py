from __future__ import annotations

import json
import logging

from langchain.agents import create_agent
from langchain_core.messages import AIMessage, HumanMessage
from langchain_openai import ChatOpenAI

from app.api_client import BusinessApiClient
from app.confirmation_store import ConfirmationStoreBackend
from app.config import Settings
from app.execution_context import bind_execution_context
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


def collect_knowledge_citations(messages) -> list[str]:
    """只从本轮知识检索 Tool 的真实返回值中提取用户可读引用。"""
    citations: list[str] = []
    for message in messages:
        if (
            getattr(message, "type", None) != "tool"
            or getattr(message, "name", None) != "search_business_knowledge"
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


def ensure_knowledge_citations(messages, response: str) -> str:
    """模型漏引时补充本轮检索来源，不生成 Tool 未返回的来源。"""
    citations = collect_knowledge_citations(messages)
    if not citations or any(citation in response for citation in citations):
        return response
    return f"{response.rstrip()}\n\n检索来源：{'；'.join(citations)}"


def build_agent(
    settings: Settings,
    client: BusinessApiClient,
    user_id: int,
    skill_registry: SkillRegistry | None = None,
    checkpointer=None,
    confirmation_store: ConfirmationStoreBackend | None = None,
    knowledge_search: KnowledgeSearchService | None = None,
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
            client,
            user_id,
            registry,
            confirmation_store,
            knowledge_search,
        ),
        system_prompt=build_system_prompt(knowledge_search is not None),
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
