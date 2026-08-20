from __future__ import annotations

from langchain.agents import create_agent
from langchain_openai import ChatOpenAI

from app.api_client import BusinessApiClient
from app.config import Settings
from app.prompt import SYSTEM_PROMPT
from app.skills.registry import SkillRegistry
from app.tools import build_tools


def build_agent(
    settings: Settings,
    client: BusinessApiClient,
    user_id: int,
    skill_registry: SkillRegistry | None = None,
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
        tools=build_tools(client, user_id, registry),
        system_prompt=SYSTEM_PROMPT,
    )


def run_agent(agent, message: str) -> str:
    result = agent.invoke(
        {"messages": [{"role": "user", "content": message}]},
        config={"recursion_limit": 12},
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
