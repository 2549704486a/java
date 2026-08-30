from __future__ import annotations

import logging
import time
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

from langchain.tools import tool

from app.api_client import BusinessApiClient, BusinessApiError
from app.exchange.confirmation_store import ConfirmationStore, ConfirmationStoreBackend
from app.execution_context import current_thread_id
from app.memory.store import GrowthMemoryStore, GrowthMemoryStoreBackend
from app.knowledge.search import KnowledgeSearchError, KnowledgeSearchService
from app.services.award_recommendation import AwardRecommendationService
from app.services.controlled_exchange import ControlledExchangeService
from app.services.growth_memory import GrowthMemoryService
from app.services.points_planning import PointsPlanningService
from app.services.saved_goal_planning import SavedGoalPlanningService
from app.skills.loader import CONSUMER_SKILL_NAMES, build_load_skill_tool
from app.skills.registry import SkillRegistry
from app.trace import current_correlation_id, execute_traced


logger = logging.getLogger(__name__)


class AwardIdInput(BaseModel):
    award_id: int = Field(gt=0, description="奖品 ID，必须是正整数")


class ListAwardsInput(BaseModel):
    redeemable_only: bool = Field(
        default=False, description="是否只返回当前用户可兑换的奖品"
    )


class ListExchangeRecordsInput(BaseModel):
    award_id: int | None = Field(
        default=None,
        gt=0,
        description="只查询指定奖品时填写奖品 ID；查看全部兑换记录时留空",
    )


class PlanPointsInput(BaseModel):
    award_id: int = Field(gt=0, description="目标奖品 ID")
    excluded_task_ids: list[int] = Field(
        default_factory=list,
        description="用户明确不想参与的任务 ID；没有时传空数组",
    )
    excluded_task_names: list[str] = Field(
        default_factory=list,
        max_length=10,
        description="用户明确不想参与的任务名称；没有时传空数组",
    )
    allowed_task_names: list[str] = Field(
        default_factory=list,
        max_length=10,
        description="用户明确表示只能或只愿意完成的任务名称；没有此约束时传空数组",
    )


class PlanSavedGoalInput(BaseModel):
    goal_query: str | None = Field(
        default=None,
        max_length=300,
        description="用户对已保存目标的称呼，例如手环目标；只有一个目标时可留空",
    )
    excluded_task_ids: list[int] = Field(
        default_factory=list,
        description="用户明确不想参与的任务 ID；没有时传空数组",
    )
    excluded_task_names: list[str] = Field(
        default_factory=list,
        max_length=10,
        description="用户明确不想参与的任务名称；没有时传空数组",
    )
    allowed_task_names: list[str] = Field(
        default_factory=list,
        max_length=10,
        description="用户明确表示只能或只愿意完成的任务名称；没有此约束时传空数组",
    )


class RecommendAwardsInput(BaseModel):
    limit: int = Field(
        default=3,
        ge=1,
        le=5,
        description="推荐奖品数量，用户说推荐一个时传 1",
    )


class KnowledgeSearchInput(BaseModel):
    query: str = Field(
        min_length=2,
        max_length=300,
        description="需要查询的稳定业务规则或操作说明，保留用户问题中的关键语义",
    )
    limit: int = Field(default=3, ge=1, le=5, description="最多返回的知识片段数")


class SaveRedemptionGoalInput(BaseModel):
    award_id: int = Field(gt=0, description="用户希望长期兑换的目标奖品 ID")
    target_date: date = Field(description="用户计划完成兑换的目标日期，格式 YYYY-MM-DD")


class RememberUserMemoryInput(BaseModel):
    memory_type: Literal["preference", "goal", "profile"] = Field(
        description="记忆类型：稳定偏好、长期目标或相对稳定的个人信息"
    )
    raw_text: str = Field(
        min_length=1,
        max_length=500,
        description="忠实保留用户表达的原文，不要改写成业务字段列表",
    )
    subject: str | None = Field(
        default=None,
        max_length=100,
        description="可选主题，例如小鸟、手环、数码商品；无法确定时留空",
    )
    polarity: Literal["LIKE", "DISLIKE"] | None = Field(
        default=None,
        description="仅偏好有明确喜欢或不喜欢时填写",
    )
    time_expression: str | None = Field(
        default=None,
        max_length=100,
        description="用户原始时间表达，例如明年；没有时留空",
    )
    target_year: int | None = Field(
        default=None,
        ge=2000,
        le=2100,
        description="能够无歧义换算时填写目标年份，否则留空",
    )


class GetGrowthMemoryInput(BaseModel):
    query: str | None = Field(
        default=None,
        max_length=300,
        description="当前问题或任务中的记忆检索语义；读取相关记忆时应传入",
    )
    memory_types: list[Literal["preference", "goal", "profile", "episode"]] = Field(
        default_factory=list,
        max_length=4,
        description="当前任务真正需要的记忆类型；不确定时传空数组",
    )
    limit: int = Field(default=5, ge=1, le=20, description="最多返回的相关记忆条数")
    include_all: bool = Field(
        default=False,
        description="只有用户明确要求查看全部长期记忆时才设为 true",
    )


class SaveUserPreferencesInput(BaseModel):
    preferred_categories: list[str] = Field(
        default_factory=list,
        max_length=10,
        description="用户明确喜欢的稳定奖品类别；未提及时传空数组",
    )
    disliked_categories: list[str] = Field(
        default_factory=list,
        max_length=10,
        description="用户明确不喜欢的稳定奖品类别；未提及时传空数组",
    )
    task_preferences: list[str] = Field(
        default_factory=list,
        max_length=10,
        description="用户明确偏好的稳定任务类型；未提及时传空数组",
    )


class ForgetGrowthMemoryInput(BaseModel):
    scope: Literal["goal", "preferences", "profile", "all"] = Field(
        description="要遗忘的范围：兑换目标、偏好或全部长期记忆"
    )


def build_tools(
    client: BusinessApiClient,
    user_id: int,
    skill_registry: SkillRegistry | None = None,
    confirmation_store: ConfirmationStoreBackend | None = None,
    knowledge_search: KnowledgeSearchService | None = None,
    growth_memory_store: GrowthMemoryStoreBackend | None = None,
):
    registry = skill_registry or SkillRegistry()
    load_skill = build_load_skill_tool(registry, CONSUMER_SKILL_NAMES)
    points_manifest = registry.require_manifest("points-planning")
    recommendation_manifest = registry.require_manifest("award-recommendation")
    exchange_manifest = registry.require_manifest("controlled-exchange")
    memory_manifest = registry.require_manifest("growth-memory")
    active_memory_store = growth_memory_store or GrowthMemoryStore()
    points_service = PointsPlanningService(client)
    saved_goal_service = SavedGoalPlanningService(
        client,
        active_memory_store,
        points_service,
    )
    recommendation_service = AwardRecommendationService(client)
    controlled_exchange_service = ControlledExchangeService(
        client,
        confirmation_store or ConfirmationStore(),
    )
    growth_memory_service = GrowthMemoryService(
        client,
        active_memory_store,
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
        """查询当前登录用户的实时积分。用户只问积分时单独使用，不为丰富回答追加奖品或任务查询。"""
        return safe_result("get_user_points", {}, lambda: client.get_user_points(user_id))

    @tool
    def list_available_tasks() -> dict:
        """用户只想查看任务时，查询可参与或已完成待领奖的有效任务；制定积分方案时改用规划 Skill。"""
        return safe_result(
            "list_available_tasks",
            {},
            lambda: client.list_available_tasks(user_id),
        )

    @tool(args_schema=AwardIdInput)
    def get_award_detail(award_id: int) -> dict:
        """按奖品 ID 查询价格、库存和活动时间等实时详情；只问能否兑换时改用资格检查工具。"""
        return safe_result(
            "get_award_detail",
            {"award_id": award_id},
            lambda: client.get_award_detail(award_id),
        )

    @tool(args_schema=ListAwardsInput)
    def list_awards(redeemable_only: bool = False) -> dict:
        """查询全部奖品，或按用户提供的奖品名称解析内部 ID。名称匹配不唯一时展示候选让用户选择；需要个性化推荐时改用推荐 Skill。"""
        return safe_result(
            "list_awards",
            {"redeemable_only": redeemable_only},
            lambda: client.list_awards(user_id, redeemable_only),
        )

    @tool(args_schema=AwardIdInput)
    def check_exchange_eligibility(award_id: int) -> dict:
        """仅用于“能否兑换、是否满足条件、还差多少”等资格咨询，并返回当前积分、所需积分和缺口；用户明确要求兑换或换奖品时改用 prepare_exchange，无需再查询积分或奖品详情。"""
        return safe_result(
            "check_exchange_eligibility",
            {"award_id": award_id},
            lambda: client.check_exchange_eligibility(user_id, award_id)
        )

    @tool(args_schema=ListExchangeRecordsInput)
    def list_my_exchange_records(award_id: int | None = None) -> dict:
        """查询当前用户真实的订单、兑换记录和最终状态，可按奖品 ID 过滤；处理中不能解释为成功。"""
        return safe_result(
            "list_my_exchange_records",
            {"award_id": award_id},
            lambda: client.list_exchange_records(user_id, award_id),
        )

    @tool(
        args_schema=PlanPointsInput,
        description=(
            f"{points_manifest.tool_description}"
            "本工具内部已完成资格、奖品和实时任务查询，不要在前后重复调用基础工具。"
            "用户按名称排除任务或限定可做任务时，直接填写 excluded_task_names "
            "或 allowed_task_names，规划 Service 会基于实时任务完成匹配。"
        ),
        extras=points_manifest.trace_metadata(),
    )
    def plan_points_for_award(
        award_id: int,
        excluded_task_ids: list[int] | None = None,
        excluded_task_names: list[str] | None = None,
        allowed_task_names: list[str] | None = None,
    ) -> dict:
        arguments = {
            "award_id": award_id,
            "excluded_task_ids": excluded_task_ids or [],
            "excluded_task_names": excluded_task_names or [],
            "allowed_task_names": allowed_task_names or [],
        }

        def execute() -> dict:
            started = time.perf_counter()
            plan = points_service.plan(user_id=user_id, **arguments)
            logger.info(
                "business_service_complete service=points_planning "
                "status=%s elapsed_ms=%.2f",
                plan.status,
                (time.perf_counter() - started) * 1000,
            )
            return plan.model_dump(mode="json")

        return execute_traced("plan_points_for_award", arguments, execute)

    @tool(
        args_schema=PlanSavedGoalInput,
        description=(
            "仅在已经加载 points-planning Skill 后使用。"
            "用户要求为已经保存的长期目标制定积分计划时使用。"
            "本工具会通过规划 Service 读取目标、确定性解析当前奖品并查询实时积分、资格和任务；"
            "不要在前后重复调用 get_growth_memory、list_awards 或 plan_points_for_award。"
            "没有目标或目标过期时提示新增或更新；存在多个目标或多个匹配奖品时"
            "只返回候选让用户选择，不替用户猜测。"
        ),
        extras=points_manifest.trace_metadata(),
    )
    def plan_points_for_saved_goal(
        goal_query: str | None = None,
        excluded_task_ids: list[int] | None = None,
        excluded_task_names: list[str] | None = None,
        allowed_task_names: list[str] | None = None,
    ) -> dict:
        arguments = {
            "goal_query_chars": len(goal_query or ""),
            "excluded_task_ids": excluded_task_ids or [],
            "excluded_task_names": excluded_task_names or [],
            "allowed_task_names": allowed_task_names or [],
        }

        def execute() -> dict:
            started = time.perf_counter()
            result = saved_goal_service.plan(
                user_id=user_id,
                goal_query=goal_query,
                excluded_task_ids=excluded_task_ids or [],
                excluded_task_names=excluded_task_names or [],
                allowed_task_names=allowed_task_names or [],
            )
            logger.info(
                "business_service_complete service=saved_goal_planning "
                "status=%s elapsed_ms=%.2f",
                result.status,
                (time.perf_counter() - started) * 1000,
            )
            return result.model_dump(mode="json")

        return execute_traced("plan_points_for_saved_goal", arguments, execute)

    @tool(
        args_schema=RecommendAwardsInput,
        description=(
            f"{recommendation_manifest.tool_description}"
            "本工具内部已查询实时积分和奖品资格，不要重复调用积分或奖品列表工具；"
            "用户明确要查看全部奖品而不是推荐时改用 list_awards。"
        ),
        extras=recommendation_manifest.trace_metadata(),
    )
    def recommend_awards(limit: int = 3) -> dict:
        arguments = {"limit": limit}

        def execute() -> dict:
            started = time.perf_counter()
            recommendation = recommendation_service.recommend(user_id, limit)
            logger.info(
                "business_service_complete service=award_recommendation "
                "status=%s elapsed_ms=%.2f",
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
            "仅在已经加载 controlled-exchange Skill 后使用。"
            "用户明确表示“我想兑换、帮我兑换、换这个奖品”时直接使用，不要先调用资格检查。"
            "它只检查实时条件并生成一次性确认摘要，"
            "不会立即扣积分或提交兑换，且内部已完成资格检查，不要提前重复检查。"
            "若用户要求跳过、不用或绕过确认，不得调用本工具。"
        ),
        extras=exchange_manifest.trace_metadata(),
    )
    def prepare_exchange(award_id: int) -> dict:
        arguments = {"award_id": award_id}

        def execute() -> dict:
            context_error = exchange_context_error()
            if context_error is not None:
                return context_error
            result = controlled_exchange_service.prepare(
                user_id=user_id,
                session_id=current_thread_id() or "",
                request_id=current_correlation_id() or "-",
                award_id=award_id,
            )
            logger.info(
                "business_service_complete service=controlled_exchange status=%s",
                result.code,
            )
            payload = result.model_dump(mode="json")
            # 确认凭证只留在服务端存储中；模型只需要展示业务摘要。
            if isinstance(payload.get("data"), dict):
                payload["data"].pop("confirmationId", None)
            return payload

        return execute_traced("prepare_exchange", arguments, execute)

    @tool(
        description=(
            "仅在已经加载 controlled-exchange Skill 后使用。"
            "用户明确表示取消、不换了时使用，使当前会话尚未使用的兑换确认立即失效。"
        ),
        extras=exchange_manifest.trace_metadata(),
    )
    def cancel_exchange() -> dict:
        def execute() -> dict:
            context_error = exchange_context_error()
            if context_error is not None:
                return context_error
            result = controlled_exchange_service.cancel(
                user_id=user_id,
                session_id=current_thread_id() or "",
            )
            return result.model_dump(mode="json")

        return execute_traced("cancel_exchange", {}, execute)

    @tool(
        args_schema=GetGrowthMemoryInput,
        description=(
            "仅在已经加载 growth-memory Skill 后使用。"
            "只有用户明确引用之前保存的目标或偏好，或当前任务确实需要历史个性化信息时，"
            "才按当前问题读取少量相关长期记忆；用户已在本轮明确目标或条件时不要调用。"
            "业务过程中传 query、需要的 memory_types 和较小 limit；"
            "只有用户明确要求查看全部记忆时才设置 include_all=true。"
            "不得用它查询实时积分、库存、任务完成状态或订单状态。"
        ),
        extras=memory_manifest.trace_metadata(),
    )
    def get_growth_memory(
        query: str | None = None,
        memory_types: list[str] | None = None,
        limit: int = 5,
        include_all: bool = False,
    ) -> dict:
        arguments = {
            "query_chars": len(query or ""),
            "memory_types": memory_types or [],
            "limit": limit,
            "include_all": include_all,
        }
        return execute_traced(
            "get_growth_memory",
            arguments,
            lambda: growth_memory_service.get(
                user_id,
                query=query,
                memory_types=memory_types,
                limit=limit,
                include_all=include_all,
            ).model_dump(mode="json"),
        )

    @tool(
        args_schema=RememberUserMemoryInput,
        description=(
            "仅在已经加载 growth-memory Skill 后使用。"
            "用户直接表达跨会话仍有价值的偏好、目标或稳定个人信息时使用。"
            "原文可以宽泛或不完整，不得为了保存记忆追问奖品 ID、精确日期或业务分类；"
            "结构化字段只是可选辅助。这是新增或更新单条原子记忆的默认工具；"
            "临时条件、实时业务事实、敏感信息和模型推测不得写入。"
        ),
        extras=memory_manifest.trace_metadata(),
    )
    def remember_user_memory(
        memory_type: str,
        raw_text: str,
        subject: str | None = None,
        polarity: str | None = None,
        time_expression: str | None = None,
        target_year: int | None = None,
    ) -> dict:
        arguments = {
            "memory_type": memory_type,
            "raw_text_chars": len(raw_text),
            "has_subject": bool(subject),
            "has_time_expression": bool(time_expression),
        }

        def execute() -> dict:
            context_error = exchange_context_error()
            if context_error is not None:
                return context_error
            return growth_memory_service.remember(
                user_id=user_id,
                session_id=current_thread_id() or "",
                memory_type=memory_type,
                raw_text=raw_text,
                subject=subject,
                polarity=polarity,
                time_expression=time_expression,
                target_year=target_year,
            ).model_dump(mode="json")

        return execute_traced("remember_user_memory", arguments, execute)

    @tool(
        args_schema=SaveRedemptionGoalInput,
        description=(
            "仅在已经加载 growth-memory Skill 后使用。"
            "只有用户已经明确给出奖品 ID 和精确目标日期，并希望保存绑定业务对象的"
            "兑换目标时使用。宽泛或不完整的目标应使用 remember_user_memory 保留原文；"
            "不能根据猜测或一次性计划自动写入。"
        ),
        extras=memory_manifest.trace_metadata(),
    )
    def save_redemption_goal(award_id: int, target_date: date) -> dict:
        arguments = {
            "award_id": award_id,
            "target_date": target_date.isoformat(),
        }

        def execute() -> dict:
            context_error = exchange_context_error()
            if context_error is not None:
                return context_error
            return growth_memory_service.save_goal(
                user_id=user_id,
                session_id=current_thread_id() or "",
                award_id=award_id,
                target_date=target_date,
            ).model_dump(mode="json")

        return execute_traced("save_redemption_goal", arguments, execute)

    @tool(
        args_schema=SaveUserPreferencesInput,
        description=(
            "仅在已经加载 growth-memory Skill 后使用。"
            "只有用户明确要求用一组完整列表替换现有奖品类别、排斥类别或任务偏好时使用。"
            "单条自然语言偏好应使用 remember_user_memory，避免覆盖其他既有偏好；"
            "不能保存本轮临时条件、临时情绪或模型推测。"
        ),
        extras=memory_manifest.trace_metadata(),
    )
    def save_user_preferences(
        preferred_categories: list[str] | None = None,
        disliked_categories: list[str] | None = None,
        task_preferences: list[str] | None = None,
    ) -> dict:
        arguments = {
            "preferred_count": len(preferred_categories or []),
            "disliked_count": len(disliked_categories or []),
            "task_preference_count": len(task_preferences or []),
        }

        def execute() -> dict:
            context_error = exchange_context_error()
            if context_error is not None:
                return context_error
            return growth_memory_service.save_preferences(
                user_id=user_id,
                session_id=current_thread_id() or "",
                preferred_categories=preferred_categories or [],
                disliked_categories=disliked_categories or [],
                task_preferences=task_preferences or [],
            ).model_dump(mode="json")

        return execute_traced("save_user_preferences", arguments, execute)

    @tool(
        args_schema=ForgetGrowthMemoryInput,
        description=(
            "仅在已经加载 growth-memory Skill 后使用。"
            "用户明确要求遗忘已保存的兑换目标、偏好或全部长期记忆时使用。"
            "按用户明确指定的范围立即删除。"
        ),
        extras=memory_manifest.trace_metadata(),
    )
    def forget_growth_memory(scope: str) -> dict:
        arguments = {"scope": scope}

        def execute() -> dict:
            context_error = exchange_context_error()
            if context_error is not None:
                return context_error
            return growth_memory_service.forget(
                user_id=user_id,
                scope=scope,
            ).model_dump(mode="json")

        return execute_traced("forget_growth_memory", arguments, execute)

    available_tools = [
        load_skill,
        get_user_points,
        list_available_tasks,
        get_award_detail,
        list_awards,
        check_exchange_eligibility,
        list_my_exchange_records,
        plan_points_for_award,
        plan_points_for_saved_goal,
        recommend_awards,
        prepare_exchange,
        cancel_exchange,
        get_growth_memory,
        remember_user_memory,
        save_redemption_goal,
        save_user_preferences,
        forget_growth_memory,
    ]
    if knowledge_search is not None:
        @tool(args_schema=KnowledgeSearchInput)
        def search_business_knowledge(query: str, limit: int = 3) -> dict:
            """查询稳定的积分、任务、兑换规则和 Agent 使用说明。不得用于查询实时积分、库存、活动时间、资格或订单状态。"""
            # 用户问题可能包含隐私，轨迹只保留长度和数量，不复制查询正文。
            arguments = {"query_chars": len(query), "limit": limit}

            def execute() -> dict:
                try:
                    return knowledge_search.search(query, limit).as_dict()
                except KnowledgeSearchError:
                    logger.warning("knowledge_search_unavailable", exc_info=True)
                    return {
                        "success": False,
                        "code": "KNOWLEDGE_SEARCH_FAILED",
                        "data": None,
                        "message": "业务知识检索暂时不可用",
                        "retryable": True,
                    }

            return execute_traced("search_business_knowledge", arguments, execute)

        available_tools.append(search_business_knowledge)
    return available_tools
