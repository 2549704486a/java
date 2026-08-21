from __future__ import annotations

import logging
import time

from pydantic import BaseModel, Field

from langchain.tools import tool

from app.api_client import BusinessApiClient, BusinessApiError
from app.confirmation_store import ConfirmationStore, ConfirmationStoreBackend
from app.execution_context import current_thread_id
from app.skills.award_recommendation import AwardRecommendationSkill
from app.skills.controlled_exchange import ControlledExchangeSkill
from app.skills.points_plan import PointsPlanningSkill
from app.skills.registry import SkillRegistry
from app.trace import current_correlation_id, execute_traced


logger = logging.getLogger(__name__)


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


class RecommendAwardsInput(BaseModel):
    limit: int = Field(
        default=3,
        ge=1,
        le=5,
        description="推荐奖品数量，用户说推荐一个时传 1",
    )


def build_tools(
    client: BusinessApiClient,
    user_id: int,
    skill_registry: SkillRegistry | None = None,
    confirmation_store: ConfirmationStoreBackend | None = None,
):
    registry = skill_registry or SkillRegistry()
    points_manifest = registry.require_manifest("points-planning")
    recommendation_manifest = registry.require_manifest("award-recommendation")
    exchange_manifest = registry.require_manifest("controlled-exchange")
    points_skill = PointsPlanningSkill(client)
    recommendation_skill = AwardRecommendationSkill(client)
    controlled_exchange_skill = ControlledExchangeSkill(
        client,
        confirmation_store or ConfirmationStore(),
    )

    def safe_result(tool_name: str, arguments: dict, callable_):
        # 基础 Tool 统一完成：调用业务接口、规范化业务错误、写入执行轨迹。
        def execute() -> dict:
            try:
                return callable_().model_dump(mode="json")
            except BusinessApiError as exc:
                # 可预期的业务接口异常转成结构化结果，供模型决定如何回复用户。
                return exc.as_envelope().model_dump(mode="json")

        return execute_traced(tool_name, arguments, execute)

    @tool
    def get_user_points() -> dict:
        """查询当前登录用户的实时积分。仅在用户询问积分时使用。"""
        return safe_result("get_user_points", {}, lambda: client.get_user_points(user_id))

    @tool
    def list_available_tasks() -> dict:
        """查询当前用户可参与或已完成待领奖的有效任务，不返回已领奖任务。"""
        return safe_result(
            "list_available_tasks",
            {},
            lambda: client.list_available_tasks(user_id),
        )

    @tool(args_schema=AwardIdInput)
    def get_award_detail(award_id: int) -> dict:
        """按奖品 ID 查询奖品价格、库存和活动时间等实时详情。"""
        return safe_result(
            "get_award_detail",
            {"award_id": award_id},
            lambda: client.get_award_detail(award_id),
        )

    @tool(args_schema=ListAwardsInput)
    def list_awards(redeemable_only: bool = False) -> dict:
        """查询奖品列表；用户未明确奖品 ID、希望查看可选奖品时使用。"""
        return safe_result(
            "list_awards",
            {"redeemable_only": redeemable_only},
            lambda: client.list_awards(user_id, redeemable_only),
        )

    @tool(args_schema=AwardIdInput)
    def check_exchange_eligibility(award_id: int) -> dict:
        """检查当前用户是否满足指定奖品的兑换条件，并返回准确原因和积分缺口。"""
        return safe_result(
            "check_exchange_eligibility",
            {"award_id": award_id},
            lambda: client.check_exchange_eligibility(user_id, award_id)
        )

    @tool(
        args_schema=PlanPointsInput,
        description=points_manifest.tool_description,
        extras=points_manifest.trace_metadata(),
    )
    def plan_points_for_award(
        award_id: int, excluded_task_ids: list[int] | None = None
    ) -> dict:
        arguments = {
            "award_id": award_id,
            "excluded_task_ids": excluded_task_ids or [],
        }

        def execute() -> dict:
            # Skill 激活时加载清单与正文，再执行由多个业务查询组成的确定性流程。
            started = time.perf_counter()
            active_definition = registry.activate(points_manifest.name)
            plan = points_skill.plan(user_id=user_id, **arguments)
            logger.info(
                "skill_complete name=%s version=%s status=%s elapsed_ms=%.2f",
                active_definition.manifest.name,
                active_definition.manifest.version,
                plan.status,
                (time.perf_counter() - started) * 1000,
            )
            return plan.model_dump(mode="json")

        return execute_traced("plan_points_for_award", arguments, execute)

    @tool(
        args_schema=RecommendAwardsInput,
        description=recommendation_manifest.tool_description,
        extras=recommendation_manifest.trace_metadata(),
    )
    def recommend_awards(limit: int = 3) -> dict:
        arguments = {"limit": limit}

        def execute() -> dict:
            # 外层轨迹把整个 Skill 视为一次 Agent 工具调用，便于统计端到端耗时。
            started = time.perf_counter()
            active_definition = registry.activate(recommendation_manifest.name)
            recommendation = recommendation_skill.recommend(user_id, limit)
            logger.info(
                "skill_complete name=%s version=%s status=%s elapsed_ms=%.2f",
                active_definition.manifest.name,
                active_definition.manifest.version,
                recommendation.status,
                (time.perf_counter() - started) * 1000,
            )
            return recommendation.model_dump(mode="json")

        return execute_traced("recommend_awards", arguments, execute)

    def exchange_context_error() -> dict | None:
        if current_thread_id() is not None:
            return None
        return {
            "success": False,
            "code": "EXECUTION_CONTEXT_UNAVAILABLE",
            "data": None,
            "message": "当前调用缺少安全会话上下文，不能执行兑换操作",
            "retryable": False,
        }

    @tool(
        args_schema=AwardIdInput,
        description=(
            "用户明确表示想兑换指定奖品时使用。它只检查实时条件并生成一次性确认摘要，"
            "不会立即扣积分或提交兑换。若用户要求跳过、不用或绕过确认，不得调用本工具。"
        ),
        extras=exchange_manifest.trace_metadata(),
    )
    def prepare_exchange(award_id: int) -> dict:
        arguments = {"award_id": award_id}

        def execute() -> dict:
            context_error = exchange_context_error()
            if context_error is not None:
                return context_error
            active_definition = registry.activate(exchange_manifest.name)
            result = controlled_exchange_skill.prepare(
                user_id=user_id,
                session_id=current_thread_id() or "",
                request_id=current_correlation_id() or "-",
                award_id=award_id,
            )
            logger.info(
                "skill_complete name=%s version=%s status=%s",
                active_definition.manifest.name,
                active_definition.manifest.version,
                result.code,
            )
            payload = result.model_dump(mode="json")
            # 确认凭证只留在服务端存储中；模型只需要展示业务摘要。
            if isinstance(payload.get("data"), dict):
                payload["data"].pop("confirmationId", None)
            return payload

        return execute_traced("prepare_exchange", arguments, execute)

    @tool(
        description="用户明确表示取消、不换了时使用，使当前会话尚未使用的兑换确认立即失效。",
        extras=exchange_manifest.trace_metadata(),
    )
    def cancel_exchange() -> dict:
        def execute() -> dict:
            context_error = exchange_context_error()
            if context_error is not None:
                return context_error
            result = controlled_exchange_skill.cancel(
                user_id=user_id,
                session_id=current_thread_id() or "",
            )
            return result.model_dump(mode="json")

        return execute_traced("cancel_exchange", {}, execute)

    return [
        get_user_points,
        list_available_tasks,
        get_award_detail,
        list_awards,
        check_exchange_eligibility,
        plan_points_for_award,
        recommend_awards,
        prepare_exchange,
        cancel_exchange,
    ]
