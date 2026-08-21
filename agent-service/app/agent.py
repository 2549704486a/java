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
from app.prompt import SYSTEM_PROMPT
from app.skills.registry import SkillRegistry
from app.tools import build_tools
from app.trace import capture_tool_trace


logger = logging.getLogger(__name__)


def build_agent(
    settings: Settings,
    client: BusinessApiClient,
    user_id: int,
    skill_registry: SkillRegistry | None = None,
    checkpointer=None,
    confirmation_store: ConfirmationStoreBackend | None = None,
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
        tools=build_tools(client, user_id, registry, confirmation_store),
        system_prompt=SYSTEM_PROMPT,
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
    final_message = result["messages"][-1]
    content = final_message.content
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
