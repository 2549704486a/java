from __future__ import annotations

from pydantic import BaseModel, Field

from langchain.tools import tool

from app.api_client import BusinessApiClient, BusinessApiError
from app.skills.points_plan import PointsPlanningSkill


class AwardIdInput(BaseModel):
    award_id: int = Field(gt=0, description="奖品 ID，必须是正整数")


class ListAwardsInput(BaseModel):
    redeemable_only: bool = Field(
        default=False, description="是否只返回当前用户可兑换的奖品"
    )


class PlanPointsInput(BaseModel):
    award_id: int = Field(gt=0, description="目标奖品 ID")
    excluded_task_ids: list[int] = Field(
        default_factory=list,
        description="用户明确不想参与的任务 ID；没有时传空数组",
    )


def build_tools(client: BusinessApiClient, user_id: int):
    skill = PointsPlanningSkill(client)

    def safe_result(callable_):
        try:
            return callable_().model_dump(mode="json")
        except BusinessApiError as exc:
            return exc.as_envelope().model_dump(mode="json")

    @tool
    def get_user_points() -> dict:
        """查询当前登录用户的实时积分。仅在用户询问积分时使用。"""
        return safe_result(lambda: client.get_user_points(user_id))

    @tool
    def list_available_tasks() -> dict:
        """查询当前用户可参与或已完成待领奖的有效任务，不返回已领奖任务。"""
        return safe_result(lambda: client.list_available_tasks(user_id))

    @tool(args_schema=AwardIdInput)
    def get_award_detail(award_id: int) -> dict:
        """按奖品 ID 查询奖品价格、库存和活动时间等实时详情。"""
        return safe_result(lambda: client.get_award_detail(award_id))

    @tool(args_schema=ListAwardsInput)
    def list_awards(redeemable_only: bool = False) -> dict:
        """查询奖品列表；用户未明确奖品 ID、希望查看可选奖品时使用。"""
        return safe_result(lambda: client.list_awards(user_id, redeemable_only))

    @tool(args_schema=AwardIdInput)
    def check_exchange_eligibility(award_id: int) -> dict:
        """检查当前用户是否满足指定奖品的兑换条件，并返回准确原因和积分缺口。"""
        return safe_result(
            lambda: client.check_exchange_eligibility(user_id, award_id)
        )

    @tool(args_schema=PlanPointsInput)
    def plan_points_for_award(
        award_id: int, excluded_task_ids: list[int] | None = None
    ) -> dict:
        """为目标奖品生成积分计划。用户问“怎么攒够积分”或要求任务组合时使用。"""
        return skill.plan(
            user_id=user_id,
            award_id=award_id,
            excluded_task_ids=excluded_task_ids or [],
        ).model_dump(mode="json")

    return [
        get_user_points,
        list_available_tasks,
        get_award_detail,
        list_awards,
        check_exchange_eligibility,
        plan_points_for_award,
    ]

