"""把命中的 SKILL.md 正文按需提供给模型。"""

from __future__ import annotations

from collections.abc import Iterable

from langchain.tools import tool
from pydantic import BaseModel, Field

from app.skills.registry import SkillDefinitionError, SkillRegistry
from app.trace import execute_traced


CONSUMER_SKILL_NAMES = (
    "points-planning",
    "award-recommendation",
    "controlled-exchange",
    "growth-memory",
)
OPERATOR_SKILL_NAMES = ("campaign-planning",)


class LoadSkillInput(BaseModel):
    skill_name: str = Field(
        min_length=1,
        max_length=80,
        description="从当前 Agent 提供的 Skill 目录中选择的准确名称",
    )


def build_load_skill_tool(
    registry: SkillRegistry,
    allowed_names: Iterable[str],
):
    allowed = tuple(dict.fromkeys(allowed_names))
    allowed_text = "、".join(allowed)

    @tool(
        args_schema=LoadSkillInput,
        description=(
            "按需加载 Skill 的完整执行说明。当前任务命中 Skill 目录中的触发条件时，"
            "必须先调用本工具，读取返回的 instructions 后再调用该 Skill 需要的业务工具。"
            f"当前允许加载：{allowed_text}。"
        ),
    )
    def load_skill(skill_name: str) -> dict:
        def execute() -> dict:
            try:
                return registry.load(
                    skill_name,
                    allowed_names=allowed,
                ).as_tool_result()
            except SkillDefinitionError as exc:
                return {
                    "success": False,
                    "code": "SKILL_NOT_AVAILABLE",
                    "data": None,
                    "message": str(exc),
                    "retryable": False,
                }

        return execute_traced(
            "load_skill",
            {"skill_name": skill_name},
            execute,
        )

    return load_skill
