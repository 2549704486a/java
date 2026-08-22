from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable, Iterable
from datetime import date

from pydantic import ValidationError

from app.api_client import BusinessApiClient, BusinessApiError
from app.growth_memory_store import GrowthMemoryStoreBackend
from app.memory_retrieval import select_memories
from app.models import (
    AwardOptionData,
    MemoryItem,
    SavedGoalAwardCandidate,
    SavedGoalCandidate,
    SavedGoalPointsPlan,
)
from app.skills.points_plan import PointsPlanningSkill


class SavedGoalPlanningSkill:
    """把已保存的长期目标解析为奖品，再复用实时积分规划。"""

    def __init__(
        self,
        client: BusinessApiClient,
        memory_store: GrowthMemoryStoreBackend,
        points_skill: PointsPlanningSkill,
        today_provider: Callable[[], date] = date.today,
    ) -> None:
        self._client = client
        self._memory_store = memory_store
        self._points_skill = points_skill
        self._today = today_provider

    def plan(
        self,
        *,
        user_id: int,
        goal_query: str | None = None,
        excluded_task_ids: Iterable[int] = (),
    ) -> SavedGoalPointsPlan:
        goals = [
            item
            for item in self._memory_store.get(user_id).memories
            if item.memory_type == "goal"
        ]
        if not goals:
            return self._result(
                "NO_SAVED_GOAL",
                "NO_SAVED_GOAL",
                "当前没有已保存的长期兑换目标",
            )

        selected_goals = self._select_goals(goals, goal_query)
        if len(selected_goals) != 1:
            return SavedGoalPointsPlan(
                status="GOAL_NEEDS_SELECTION",
                reason_code="MULTIPLE_OR_UNCLEAR_GOALS",
                message="存在多个目标或当前描述无法唯一定位目标，请先选择要规划的目标",
                goal_candidates=[self._goal_candidate(item) for item in selected_goals],
            )
        goal = selected_goals[0]
        if self._goal_expired(goal):
            return self._result(
                "GOAL_EXPIRED",
                "SAVED_GOAL_EXPIRED",
                "已保存目标的时间已经过去，请先更新目标时间",
                goal=goal,
            )

        bound_award_id = _positive_int(goal.normalized_data.get("awardId"))
        if bound_award_id is not None:
            return self._build_plan(
                user_id=user_id,
                goal=goal,
                award_id=bound_award_id,
                excluded_task_ids=excluded_task_ids,
            )

        award_options = self._list_awards(user_id, goal)
        if isinstance(award_options, SavedGoalPointsPlan):
            return award_options
        candidates = self._match_awards(goal, award_options)
        if not candidates:
            return self._result(
                "TARGET_NOT_AVAILABLE",
                "NO_MATCHING_AWARD",
                "当前奖品中没有与已保存目标明确匹配的选项",
                goal=goal,
            )
        if len(candidates) > 1:
            return SavedGoalPointsPlan(
                status="AWARD_NEEDS_SELECTION",
                reason_code="MULTIPLE_MATCHING_AWARDS",
                message="长期目标对应多个当前奖品，请先选择具体奖品",
                goal_raw_text=goal.raw_text,
                **self._goal_time_fields(goal),
                candidates=[self._candidate(option) for option in candidates],
            )
        return self._build_plan(
            user_id=user_id,
            goal=goal,
            award_id=candidates[0].award.award_id,
            excluded_task_ids=excluded_task_ids,
        )

    @staticmethod
    def _select_goals(goals: list[MemoryItem], goal_query: str | None) -> list[MemoryItem]:
        if len(goals) == 1:
            return goals
        if not goal_query or not goal_query.strip():
            return goals
        normalized_query = _normalize(goal_query)
        subject_matches = [
            goal
            for goal in goals
            if _normalize(str(goal.normalized_data.get("subject", "")))
            and _normalize(str(goal.normalized_data.get("subject", "")))
            in normalized_query
        ]
        if subject_matches:
            return subject_matches
        # 候选集合已经限定为 goal，此处不再传类型过滤，确保无文本证据的目标不会混入。
        return select_memories(
            goals,
            query=goal_query,
            memory_types=None,
            limit=5,
            include_all=False,
        )

    def _list_awards(
        self,
        user_id: int,
        goal: MemoryItem,
    ) -> list[AwardOptionData] | SavedGoalPointsPlan:
        try:
            envelope = self._client.list_awards(user_id, False)
        except BusinessApiError as exc:
            return self._result(
                "QUERY_FAILED",
                exc.code,
                exc.message,
                goal=goal,
            )
        if not envelope.success:
            return self._result(
                "QUERY_FAILED",
                envelope.code,
                envelope.message,
                goal=goal,
            )
        try:
            return [AwardOptionData.model_validate(item) for item in envelope.data or []]
        except (TypeError, ValidationError):
            return self._result(
                "QUERY_FAILED",
                "INVALID_BUSINESS_RESPONSE",
                "奖品列表返回了无法识别的数据",
                goal=goal,
            )

    @staticmethod
    def _match_awards(
        goal: MemoryItem,
        options: list[AwardOptionData],
    ) -> list[AwardOptionData]:
        subject = str(
            goal.normalized_data.get("subject")
            or goal.normalized_data.get("target")
            or ""
        )
        normalized_subject = _normalize(subject)
        normalized_raw = _normalize(goal.raw_text)
        matches: list[AwardOptionData] = []
        for option in options:
            award_name = _normalize(option.award.name)
            if normalized_subject:
                matched = (
                    normalized_subject in award_name
                    or award_name in normalized_subject
                )
            else:
                matched = award_name in normalized_raw
            if matched:
                matches.append(option)
        return matches

    def _build_plan(
        self,
        *,
        user_id: int,
        goal: MemoryItem,
        award_id: int,
        excluded_task_ids: Iterable[int],
    ) -> SavedGoalPointsPlan:
        plan = self._points_skill.plan(
            user_id=user_id,
            award_id=award_id,
            excluded_task_ids=excluded_task_ids,
        )
        return SavedGoalPointsPlan(
            status="QUERY_FAILED" if plan.status == "QUERY_FAILED" else "TARGET_RESOLVED",
            reason_code=plan.reason_code,
            message=plan.message,
            goal_raw_text=goal.raw_text,
            **self._goal_time_fields(goal),
            plan=plan,
        )

    @staticmethod
    def _candidate(option: AwardOptionData) -> SavedGoalAwardCandidate:
        return SavedGoalAwardCandidate(
            award_id=option.award.award_id,
            name=option.award.name,
            required_points=option.award.required_points,
            inventory=option.award.inventory,
        )

    @staticmethod
    def _goal_candidate(goal: MemoryItem) -> SavedGoalCandidate:
        fields = SavedGoalPlanningSkill._goal_time_fields(goal)
        subject = goal.normalized_data.get("subject")
        return SavedGoalCandidate(
            raw_text=goal.raw_text,
            subject=str(subject) if subject else None,
            time_expression=fields["goal_time_expression"],
            target_date=fields["target_date"],
            target_year=fields["target_year"],
        )

    @staticmethod
    def _result(
        status: str,
        reason_code: str,
        message: str,
        *,
        goal: MemoryItem | None = None,
    ) -> SavedGoalPointsPlan:
        return SavedGoalPointsPlan(
            status=status,
            reason_code=reason_code,
            message=message,
            goal_raw_text=goal.raw_text if goal else None,
            **(SavedGoalPlanningSkill._goal_time_fields(goal) if goal else {}),
        )

    def _goal_expired(self, goal: MemoryItem) -> bool:
        fields = self._goal_time_fields(goal)
        target_date = fields.get("target_date")
        if isinstance(target_date, date):
            return target_date < self._today()
        target_year = fields.get("target_year")
        return isinstance(target_year, int) and target_year < self._today().year

    @staticmethod
    def _goal_time_fields(goal: MemoryItem) -> dict:
        data = goal.normalized_data
        parsed_date = None
        raw_date = data.get("targetDate")
        if isinstance(raw_date, str):
            try:
                parsed_date = date.fromisoformat(raw_date)
            except ValueError:
                parsed_date = None
        target_year = _positive_int(data.get("targetYear"))
        time_expression = data.get("timeExpression")
        return {
            "goal_time_expression": (
                str(time_expression) if time_expression is not None else None
            ),
            "target_date": parsed_date,
            "target_year": target_year,
        }


def _positive_int(value) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value > 0:
        return value
    if isinstance(value, str) and value.isdigit() and int(value) > 0:
        return int(value)
    return None


def _normalize(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", normalized)
