from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable

from pydantic import ValidationError

from app.api_client import BusinessApiClient, BusinessApiError
from app.models import (
    AwardData,
    EligibilityData,
    PointsPlan,
    RecommendedTask,
    TaskData,
    ToolEnvelope,
)


class PointsPlanningSkill:
    """组合资格、奖品和任务查询，确定性地生成积分方案。"""

    def __init__(self, client: BusinessApiClient) -> None:
        self._client = client

    def plan(
        self,
        user_id: int,
        award_id: int,
        excluded_task_ids: Iterable[int] = (),
        excluded_task_names: Iterable[str] = (),
        allowed_task_names: Iterable[str] = (),
    ) -> PointsPlan:
        if user_id <= 0 or award_id <= 0:
            return PointsPlan(
                status="QUERY_FAILED",
                reason_code="INVALID_ARGUMENT",
                message="用户 ID 和奖品 ID 必须为正整数",
                user_id=user_id,
                award_id=award_id,
            )

        try:
            eligibility_envelope = self._client.check_exchange_eligibility(
                user_id, award_id
            )
        except BusinessApiError as exc:
            return self._query_failed(user_id, award_id, exc.as_envelope())

        if not eligibility_envelope.success:
            return self._query_failed(user_id, award_id, eligibility_envelope)

        try:
            eligibility = EligibilityData.model_validate(eligibility_envelope.data)
        except ValidationError:
            return self._invalid_response(user_id, award_id, "兑换资格")
        if eligibility.eligible:
            award_name = self._safe_award_name(award_id)
            return PointsPlan(
                status="READY_TO_EXCHANGE",
                reason_code=eligibility.reason_code,
                message="当前积分和奖品条件均满足，可以前往兑换页面操作",
                user_id=user_id,
                award_id=award_id,
                award_name=award_name,
                current_points=eligibility.current_points,
                required_points=eligibility.required_points,
                points_gap=0,
                projected_points=eligibility.current_points,
                remaining_gap=0,
            )

        if eligibility.reason_code != "INSUFFICIENT_POINTS":
            return PointsPlan(
                status="BLOCKED",
                reason_code=eligibility.reason_code,
                message=eligibility.reason,
                user_id=user_id,
                award_id=award_id,
                current_points=eligibility.current_points,
                required_points=eligibility.required_points,
                points_gap=eligibility.points_gap,
                projected_points=eligibility.current_points,
                remaining_gap=eligibility.points_gap,
            )

        try:
            award_envelope = self._client.get_award_detail(award_id)
            tasks_envelope = self._client.list_available_tasks(user_id)
        except BusinessApiError as exc:
            return self._query_failed(user_id, award_id, exc.as_envelope())

        if not award_envelope.success:
            return self._query_failed(user_id, award_id, award_envelope)
        if not tasks_envelope.success:
            return self._query_failed(user_id, award_id, tasks_envelope)

        try:
            award = AwardData.model_validate(award_envelope.data)
            task_items = tasks_envelope.data or []
            tasks = [TaskData.model_validate(item) for item in task_items]
        except (ValidationError, TypeError):
            return self._invalid_response(user_id, award_id, "奖品或任务")

        excluded = set(excluded_task_ids)
        excluded_names = self._normalize_constraints(excluded_task_names)
        allowed_names = self._normalize_constraints(allowed_task_names)
        tasks = [
            task
            for task in tasks
            if task.task_id not in excluded
            and not self._matches_any_name(task.task_name, excluded_names)
            and (
                not allowed_names
                or self._matches_any_name(task.task_name, allowed_names)
            )
            and task.reward_points > 0
            and task.status != "REWARDED"
        ]
        selected = self._select_tasks(tasks, eligibility.points_gap)
        recommended_points = sum(task.reward_points for task in selected)
        remaining_gap = max(0, eligibility.points_gap - recommended_points)
        recommended_tasks = [self._to_recommendation(task) for task in selected]

        if remaining_gap == 0:
            status = "PLAN_READY"
            message = "当前可用任务能够覆盖积分缺口"
        else:
            status = "INSUFFICIENT_TASK_REWARDS"
            message = f"当前可用任务仍不足以覆盖积分缺口，还差 {remaining_gap} 积分"

        return PointsPlan(
            status=status,
            reason_code=eligibility.reason_code,
            message=message,
            user_id=user_id,
            award_id=award_id,
            award_name=award.name,
            current_points=eligibility.current_points,
            required_points=eligibility.required_points,
            points_gap=eligibility.points_gap,
            recommended_points=recommended_points,
            projected_points=eligibility.current_points + recommended_points,
            remaining_gap=remaining_gap,
            recommended_tasks=recommended_tasks,
        )

    def _safe_award_name(self, award_id: int) -> str | None:
        try:
            envelope = self._client.get_award_detail(award_id)
        except BusinessApiError:
            return None
        if not envelope.success or not envelope.data:
            return None
        try:
            return AwardData.model_validate(envelope.data).name
        except ValidationError:
            return None

    @classmethod
    def _select_tasks(cls, tasks: list[TaskData], gap: int) -> list[TaskData]:
        if gap <= 0:
            return []

        unclaimed = sorted(
            (task for task in tasks if task.status == "COMPLETED_UNCLAIMED"),
            key=cls._task_sort_key,
        )
        available = sorted(
            (task for task in tasks if task.status == "AVAILABLE"),
            key=cls._task_sort_key,
        )

        selected_unclaimed = cls._smallest_cover(unclaimed, gap)
        unclaimed_points = sum(task.reward_points for task in selected_unclaimed)
        if unclaimed_points >= gap:
            return selected_unclaimed

        # 已完成待领取的积分成本最低，数量不足时先全部领取，再规划未完成任务。
        selected_unclaimed = unclaimed
        remaining = gap - sum(task.reward_points for task in selected_unclaimed)
        selected_available = cls._smallest_cover(available, remaining)
        return selected_unclaimed + selected_available

    @staticmethod
    def _task_sort_key(task: TaskData) -> tuple[int, int]:
        return (-task.reward_points, task.task_id)

    @staticmethod
    def _normalize_constraints(values: Iterable[str]) -> set[str]:
        return {
            normalized
            for value in values
            if (normalized := _normalize_task_name(value))
        }

    @staticmethod
    def _matches_any_name(task_name: str, constraints: set[str]) -> bool:
        normalized_task = _normalize_task_name(task_name)
        return any(
            constraint in normalized_task or normalized_task in constraint
            for constraint in constraints
        )

    @classmethod
    def _smallest_cover(cls, tasks: list[TaskData], target: int) -> list[TaskData]:
        if target <= 0 or not tasks:
            return []
        if sum(task.reward_points for task in tasks) < target:
            return tasks

        max_reward = max(task.reward_points for task in tasks)
        max_sum = target + max_reward - 1
        states: dict[int, tuple[TaskData, ...]] = {0: ()}
        for task in tasks:
            updates = dict(states)
            for points, chosen in states.items():
                new_points = points + task.reward_points
                if new_points > max_sum:
                    continue
                candidate = chosen + (task,)
                existing = updates.get(new_points)
                if existing is None or cls._subset_key(candidate) < cls._subset_key(
                    existing
                ):
                    updates[new_points] = candidate
            states = updates

        covers = [
            (points, chosen) for points, chosen in states.items() if points >= target
        ]
        _, best = min(
            covers,
            key=lambda item: (
                len(item[1]),
                item[0] - target,
                tuple(task.task_id for task in item[1]),
            ),
        )
        return list(best)

    @staticmethod
    def _subset_key(tasks: tuple[TaskData, ...]) -> tuple[int, tuple[int, ...]]:
        return len(tasks), tuple(task.task_id for task in tasks)

    @staticmethod
    def _to_recommendation(task: TaskData) -> RecommendedTask:
        return RecommendedTask(
            task_id=task.task_id,
            task_name=task.task_name,
            reward_points=task.reward_points,
            status=task.status,
            action=(
                "CLAIM_REWARD"
                if task.status == "COMPLETED_UNCLAIMED"
                else "COMPLETE_TASK"
            ),
        )

    @staticmethod
    def _query_failed(
        user_id: int, award_id: int, envelope: ToolEnvelope
    ) -> PointsPlan:
        return PointsPlan(
            status="QUERY_FAILED",
            reason_code=envelope.code,
            message=envelope.message,
            user_id=user_id,
            award_id=award_id,
        )

    @staticmethod
    def _invalid_response(user_id: int, award_id: int, source: str) -> PointsPlan:
        return PointsPlan(
            status="QUERY_FAILED",
            reason_code="INVALID_BUSINESS_RESPONSE",
            message=f"{source}查询返回了无法识别的数据",
            user_id=user_id,
            award_id=award_id,
        )


def _normalize_task_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", normalized)
