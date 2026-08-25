from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Literal

from langchain.tools import tool
from pydantic import AwareDatetime, BaseModel, Field

from app.operator.campaign_data import CampaignDataProvider, CampaignDataUnavailable
from app.api_client import BusinessApiClient, BusinessApiError
from app.knowledge.search import KnowledgeSearchError, KnowledgeSearchService
from app.models import CampaignBrief
from app.operator.auth import AuthenticatedOperator, OperatorPermissionError
from app.skills.campaign_planning import CampaignPlanningSkill
from app.skills.registry import SkillRegistry
from app.trace import execute_traced


CAMPAIGN_READ = "campaign:read"
CAMPAIGN_DRAFT = "campaign:draft"
CAMPAIGN_REVIEW = "campaign:review"
CAMPAIGN_PUBLISH = "campaign:publish"
CAMPAIGN_METRIC = "campaign:metric"
OPERATOR_KNOWLEDGE_SCOPES = {
    "campaign_policy": ("campaign_policy", "rule_change_notice"),
    "award_rules": ("award_guide",),
    "operations": ("incident_manual", "delivery_guide"),
    "review_cases": ("campaign_review",),
}


class CampaignSnapshotInput(BaseModel):
    target_segment_key: str = Field(
        min_length=1,
        max_length=64,
        description=(
            "服务端支持的固定客群标识：ALL_USERS、POINTS_AT_LEAST_500、"
            "ACTIVE_LAST_7_DAYS 或 INACTIVE_30_DAYS"
        ),
    )


class CampaignDraftInput(CampaignSnapshotInput):
    objective: str = Field(min_length=2, max_length=200, description="活动目标")
    budget_amount_cents: int = Field(
        gt=0,
        description="本次活动奖品的真实现金预算，单位为分",
    )
    points_issuance_cap: int = Field(
        gt=0,
        description="本次活动任务最多发放的积分，与现金预算分别约束",
    )
    start_at: AwareDatetime = Field(description="包含时区的活动开始时间")
    end_at: AwareDatetime = Field(description="包含时区的活动结束时间")
    max_tasks: int = Field(default=2, ge=1, le=5)
    max_awards: int = Field(default=2, ge=1, le=5)


class OperatorKnowledgeSearchInput(BaseModel):
    query: str = Field(
        min_length=2,
        max_length=300,
        description="需要查询的运营制度、操作手册或历史案例",
    )
    scope: Literal[
        "campaign_policy",
        "award_rules",
        "operations",
        "review_cases",
    ] = Field(description="运营知识范围，由模型按当前任务选择")
    limit: int = Field(default=3, ge=1, le=5)


def build_operator_tools(
    data_provider: CampaignDataProvider,
    operator: AuthenticatedOperator,
    skill_registry: SkillRegistry | None = None,
    planning_skill: CampaignPlanningSkill | None = None,
    knowledge_search: KnowledgeSearchService | None = None,
    business_client: BusinessApiClient | None = None,
):
    """构建独立运营 Tool；普通用户 Agent 不会调用此函数。"""

    _require_permissions(operator, CAMPAIGN_READ)

    @tool(args_schema=CampaignSnapshotInput)
    def get_campaign_planning_snapshot(target_segment_key: str) -> dict:
        """读取活动草案所需的客群、任务、奖品库存和历史参与率快照。"""

        arguments = {
            "operator_id": operator.operator_id,
            "target_segment_key": target_segment_key,
        }

        def execute() -> dict:
            try:
                snapshot = data_provider.get_planning_snapshot(target_segment_key)
            except CampaignDataUnavailable as exc:
                return {
                    "success": False,
                    "code": exc.code,
                    "data": None,
                    "message": exc.message,
                    "retryable": exc.retryable,
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
    if knowledge_search is not None:

        @tool(args_schema=OperatorKnowledgeSearchInput)
        def search_operator_knowledge(
            query: str,
            scope: Literal[
                "campaign_policy",
                "award_rules",
                "operations",
                "review_cases",
            ],
            limit: int = 3,
        ) -> dict:
            """查询当前有效的运营制度、操作手册与历史案例，不替代实时规划快照。"""

            arguments = {
                "operator_id": operator.operator_id,
                "query_chars": len(query),
                "scope": scope,
                "limit": limit,
            }

            def execute() -> dict:
                try:
                    return knowledge_search.search(
                        query,
                        limit,
                        business_types=OPERATOR_KNOWLEDGE_SCOPES[scope],
                    ).as_dict()
                except KnowledgeSearchError:
                    return {
                        "success": False,
                        "code": "OPERATOR_KNOWLEDGE_SEARCH_FAILED",
                        "data": None,
                        "message": "运营知识检索暂时不可用",
                        "retryable": True,
                    }

            return execute_traced("search_operator_knowledge", arguments, execute)

        available_tools.append(search_operator_knowledge)

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
        target_segment_key: str,
        objective: str,
        budget_amount_cents: int,
        points_issuance_cap: int,
        start_at: datetime,
        end_at: datetime,
        max_tasks: int = 2,
        max_awards: int = 2,
    ) -> dict:
        """根据运营简报和只读事实生成不可直接发布的活动草案。"""

        arguments = {
            "operator_id": operator.operator_id,
            "budget_amount_cents": budget_amount_cents,
            "points_issuance_cap": points_issuance_cap,
            "max_tasks": max_tasks,
            "max_awards": max_awards,
        }

        def execute() -> dict:
            registry.activate(manifest.name)
            try:
                snapshot = data_provider.get_planning_snapshot(target_segment_key)
            except CampaignDataUnavailable as exc:
                return {
                    "success": False,
                    "code": exc.code,
                    "data": None,
                    "message": exc.message,
                    "retryable": exc.retryable,
                }
            brief = CampaignBrief(
                objective=objective,
                target_segment_key=target_segment_key,
                target_segment=snapshot.segment.description,
                budget_amount_cents=budget_amount_cents,
                points_issuance_cap=points_issuance_cap,
                start_at=start_at,
                end_at=end_at,
                max_tasks=max_tasks,
                max_awards=max_awards,
            )
            plan = skill.create_draft(brief, snapshot)
            plan_data = plan.model_dump(mode="json")
            if business_client is None or plan.status != "DRAFT_READY":
                return plan_data

            # The LLM proposes the brief; persistence identity and ownership are
            # bound by trusted application code rather than model arguments.
            try:
                return business_client.create_campaign_draft(
                    {
                        "draftKey": uuid.uuid4().hex,
                        "operatorId": operator.operator_id,
                        "objective": objective,
                        "targetSegmentKey": target_segment_key,
                        "targetSegment": snapshot.segment.description,
                        "budgetAmountCents": budget_amount_cents,
                        "pointsIssuanceCap": points_issuance_cap,
                        "startAt": start_at.isoformat(),
                        "endAt": end_at.isoformat(),
                        "planJson": json.dumps(
                            plan_data,
                            ensure_ascii=False,
                            separators=(",", ":"),
                        ),
                    }
                ).model_dump(mode="json")
            except BusinessApiError as exc:
                return exc.as_envelope().model_dump(mode="json")

        return execute_traced("draft_campaign_plan", arguments, execute)

    available_tools.append(draft_campaign_plan)
    return available_tools


def _require_permissions(operator: AuthenticatedOperator, *required: str) -> None:
    missing = [item for item in required if item not in operator.permissions]
    if missing:
        raise OperatorPermissionError(f"运营身份缺少权限：{', '.join(missing)}")
