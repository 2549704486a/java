from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from langchain.tools import tool
from pydantic import AwareDatetime, BaseModel, Field

from app.campaign_data import CampaignDataProvider, CampaignDataUnavailable
from app.models import CampaignBrief
from app.skills.campaign_planning import CampaignPlanningSkill
from app.skills.registry import SkillRegistry
from app.trace import execute_traced


CAMPAIGN_READ = "campaign:read"
CAMPAIGN_DRAFT = "campaign:draft"


@dataclass(frozen=True)
class OperatorContext:
    operator_id: str
    permissions: frozenset[str]


class CampaignSnapshotInput(BaseModel):
    target_segment: str = Field(
        min_length=2,
        max_length=200,
        description="已经在运营数据平台中定义的目标用户群描述",
    )


class CampaignDraftInput(CampaignSnapshotInput):
    objective: str = Field(min_length=2, max_length=200, description="活动目标")
    budget_points: int = Field(gt=0, description="本次活动最多发放的积分预算")
    start_at: AwareDatetime = Field(description="包含时区的活动开始时间")
    end_at: AwareDatetime = Field(description="包含时区的活动结束时间")
    max_tasks: int = Field(default=2, ge=1, le=5)
    max_awards: int = Field(default=2, ge=1, le=5)


def build_operator_tools(
    data_provider: CampaignDataProvider,
    operator: OperatorContext,
    skill_registry: SkillRegistry | None = None,
    planning_skill: CampaignPlanningSkill | None = None,
):
    """构建独立运营 Tool；普通用户 Agent 不会调用此函数。"""

    _require_permissions(operator, CAMPAIGN_READ)

    @tool(args_schema=CampaignSnapshotInput)
    def get_campaign_planning_snapshot(target_segment: str) -> dict:
        """读取活动草案所需的用户群、任务、奖品库存和历史参与率快照。"""

        arguments = {
            "operator_id": operator.operator_id,
            "target_segment_chars": len(target_segment),
        }

        def execute() -> dict:
            try:
                snapshot = data_provider.get_planning_snapshot(target_segment)
            except CampaignDataUnavailable as exc:
                return {
                    "success": False,
                    "code": "CAMPAIGN_DATA_UNAVAILABLE",
                    "data": None,
                    "message": str(exc),
                    "retryable": True,
                }
            return {
                "success": True,
                "code": "CAMPAIGN_SNAPSHOT_FOUND",
                "data": snapshot.model_dump(mode="json"),
                "message": "活动规划快照读取成功",
                "retryable": False,
            }

        return execute_traced("get_campaign_planning_snapshot", arguments, execute)

    available_tools = [get_campaign_planning_snapshot]
    if CAMPAIGN_DRAFT not in operator.permissions:
        return available_tools

    registry = skill_registry or SkillRegistry()
    manifest = registry.require_manifest("campaign-planning")
    skill = planning_skill or CampaignPlanningSkill()

    @tool(
        args_schema=CampaignDraftInput,
        description=manifest.tool_description,
        extras=manifest.trace_metadata(),
    )
    def draft_campaign_plan(
        target_segment: str,
        objective: str,
        budget_points: int,
        start_at: datetime,
        end_at: datetime,
        max_tasks: int = 2,
        max_awards: int = 2,
    ) -> dict:
        """根据运营简报和只读事实生成不可直接发布的活动草案。"""

        arguments = {
            "operator_id": operator.operator_id,
            "budget_points": budget_points,
            "max_tasks": max_tasks,
            "max_awards": max_awards,
        }

        def execute() -> dict:
            registry.activate(manifest.name)
            try:
                snapshot = data_provider.get_planning_snapshot(target_segment)
            except CampaignDataUnavailable as exc:
                return {
                    "success": False,
                    "code": "CAMPAIGN_DATA_UNAVAILABLE",
                    "data": None,
                    "message": str(exc),
                    "retryable": True,
                }
            brief = CampaignBrief(
                objective=objective,
                target_segment=target_segment,
                budget_points=budget_points,
                start_at=start_at,
                end_at=end_at,
                max_tasks=max_tasks,
                max_awards=max_awards,
            )
            return skill.create_draft(brief, snapshot).model_dump(mode="json")

        return execute_traced("draft_campaign_plan", arguments, execute)

    available_tools.append(draft_campaign_plan)
    return available_tools


def _require_permissions(operator: OperatorContext, *required: str) -> None:
    missing = [item for item in required if item not in operator.permissions]
    if missing:
        raise PermissionError(f"运营身份缺少权限：{', '.join(missing)}")
