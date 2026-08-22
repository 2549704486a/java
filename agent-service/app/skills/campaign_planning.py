from __future__ import annotations

import math
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from app.models import (
    CampaignAwardSnapshot,
    CampaignBrief,
    CampaignPlanDraft,
    CampaignPlanningSnapshot,
    CampaignRisk,
    CampaignTaskSnapshot,
    HistoricalCampaignMetric,
    SuggestedCampaignAward,
    SuggestedCampaignTask,
)


class CampaignPlanningSkill:
    """基于只读事实快照生成可编辑、不可直接发布的活动草案。"""

    def __init__(
        self,
        *,
        now_provider: Callable[[], datetime] = lambda: datetime.now(UTC),
        max_snapshot_age: timedelta = timedelta(hours=24),
    ) -> None:
        self._now = now_provider
        self._max_snapshot_age = max_snapshot_age

    def create_draft(
        self,
        brief: CampaignBrief,
        snapshot: CampaignPlanningSnapshot,
    ) -> CampaignPlanDraft:
        generated_at = self._now()
        base = self._base_fields(brief, snapshot, generated_at)

        if snapshot.segment.description != brief.target_segment:
            return CampaignPlanDraft(
                status="NEEDS_DATA",
                reason_code="SEGMENT_SNAPSHOT_MISMATCH",
                message="只读快照与活动目标用户群不一致，请重新获取数据",
                risks=[
                    self._risk(
                        "SEGMENT_SNAPSHOT_MISMATCH",
                        "BLOCKING",
                        "用户群定义与快照不一致，不能据此估算活动成本",
                    )
                ],
                **base,
            )

        if self._is_stale(snapshot.generated_at, generated_at):
            return CampaignPlanDraft(
                status="NEEDS_DATA",
                reason_code="STALE_PLANNING_SNAPSHOT",
                message="活动规划快照已经过期，请刷新后再生成草案",
                risks=[
                    self._risk(
                        "STALE_PLANNING_SNAPSHOT",
                        "BLOCKING",
                        "库存、任务或用户群数据可能已经变化",
                    )
                ],
                **base,
            )

        if snapshot.segment.estimated_users <= 0:
            return CampaignPlanDraft(
                status="NEEDS_DATA",
                reason_code="EMPTY_SEGMENT",
                message="目标用户群规模为空，无法估算活动成本",
                risks=[
                    self._risk(
                        "EMPTY_SEGMENT",
                        "BLOCKING",
                        "需要先补充目标用户群规模",
                    )
                ],
                **base,
            )

        participation_metric = self._latest_participation_metric(snapshot)
        if participation_metric is None:
            return CampaignPlanDraft(
                status="NEEDS_DATA",
                reason_code="PARTICIPATION_RATE_MISSING",
                message="缺少历史参与率，系统不会自行猜测成本参数",
                risks=[
                    self._risk(
                        "PARTICIPATION_RATE_MISSING",
                        "BLOCKING",
                        "需要提供同类活动历史参与率或人工估算依据",
                    )
                ],
                **base,
            )

        estimated_participants = max(
            0,
            math.ceil(snapshot.segment.estimated_users * participation_metric.value),
        )
        if estimated_participants == 0:
            return CampaignPlanDraft(
                status="CONSTRAINT_CONFLICT",
                reason_code="ZERO_EXPECTED_PARTICIPATION",
                message="历史数据下预计参与人数为零，请调整用户群或活动方案",
                estimated_participants=0,
                estimated_point_cost=0,
                risks=[
                    self._risk(
                        "ZERO_EXPECTED_PARTICIPATION",
                        "BLOCKING",
                        "当前活动目标和用户群缺少可预期的参与者",
                    )
                ],
                **base,
            )
        per_user_budget = brief.budget_points // estimated_participants
        tasks = self._select_tasks(snapshot.tasks, brief.max_tasks, per_user_budget)
        awards, excluded_awards = self._select_awards(
            snapshot.awards,
            brief,
        )

        risks: list[CampaignRisk] = []
        if not tasks:
            risks.append(
                self._risk(
                    "NO_TASK_FITS_BUDGET",
                    "BLOCKING",
                    "现有任务奖励无法放入当前人均积分预算",
                )
            )
        if not awards:
            risks.append(
                self._risk(
                    "NO_AWARD_AVAILABLE_FOR_WINDOW",
                    "BLOCKING",
                    "没有库存充足且覆盖活动时间窗口的奖品",
                )
            )

        estimated_point_cost = estimated_participants * sum(
            task.max_reward_per_user for task in tasks
        )
        if tasks and estimated_point_cost < brief.budget_points * 0.5:
            risks.append(
                self._risk(
                    "LOW_BUDGET_UTILIZATION",
                    "WARNING",
                    "当前任务组合预计使用不到一半积分预算，可由运营人员调整",
                )
            )
        if excluded_awards:
            risks.append(
                self._risk(
                    "AWARD_WINDOW_MISMATCH",
                    "WARNING",
                    f"有 {excluded_awards} 个奖品未覆盖完整活动时间窗口或库存为零",
                )
            )
        if awards:
            inventory = sum(award.inventory for award in awards)
            if inventory < estimated_participants:
                risks.append(
                    self._risk(
                        "AWARD_INVENTORY_COVERAGE_LOW",
                        "WARNING",
                        f"候选奖品库存仅覆盖预计参与人数的 {inventory}/{estimated_participants}",
                    )
                )
            risks.append(
                self._risk(
                    "AWARD_RELEVANCE_REVIEW_REQUIRED",
                    "INFO",
                    "当前仅按可用性和库存选择奖品，仍需人工审核奖品与活动目标的匹配度",
                )
            )

        blocking = any(risk.severity == "BLOCKING" for risk in risks)
        return CampaignPlanDraft(
            status="CONSTRAINT_CONFLICT" if blocking else "DRAFT_READY",
            reason_code=(
                "CAMPAIGN_CONSTRAINT_CONFLICT"
                if blocking
                else "CAMPAIGN_DRAFT_READY"
            ),
            message=(
                "活动约束存在冲突，请调整后重新生成草案"
                if blocking
                else "活动草案已生成，发布前仍需运营人员编辑和审核"
            ),
            estimated_participants=estimated_participants,
            estimated_point_cost=estimated_point_cost,
            suggested_tasks=[self._suggested_task(task) for task in tasks],
            suggested_awards=[self._suggested_award(award) for award in awards],
            risks=risks,
            **base,
        )

    @staticmethod
    def _base_fields(
        brief: CampaignBrief,
        snapshot: CampaignPlanningSnapshot,
        generated_at: datetime,
    ) -> dict:
        return {
            "objective": brief.objective,
            "target_segment": brief.target_segment,
            "budget_points": brief.budget_points,
            "start_at": brief.start_at,
            "end_at": brief.end_at,
            "source_snapshot_id": snapshot.snapshot_id,
            "source_generated_at": snapshot.generated_at,
            "generated_at": generated_at,
        }

    def _is_stale(self, snapshot_time: datetime, now: datetime) -> bool:
        if snapshot_time.tzinfo is None or now.tzinfo is None:
            return True
        age = now.astimezone(UTC) - snapshot_time.astimezone(UTC)
        return age < timedelta(0) or age > self._max_snapshot_age

    @staticmethod
    def _latest_participation_metric(
        snapshot: CampaignPlanningSnapshot,
    ) -> HistoricalCampaignMetric | None:
        metrics = [
            metric
            for metric in snapshot.historical_metrics
            if metric.metric_name == "participation_rate"
            and metric.as_of.tzinfo is not None
        ]
        return max(metrics, key=lambda metric: metric.as_of, default=None)

    @staticmethod
    def _select_tasks(
        tasks: list[CampaignTaskSnapshot],
        limit: int,
        per_user_budget: int,
    ) -> list[CampaignTaskSnapshot]:
        selected: list[CampaignTaskSnapshot] = []
        remaining = per_user_budget
        candidates = sorted(
            (task for task in tasks if task.active),
            key=lambda task: (-task.max_reward_per_user, task.task_id),
        )
        for task in candidates:
            if len(selected) >= limit:
                break
            if task.max_reward_per_user <= remaining:
                selected.append(task)
                remaining -= task.max_reward_per_user
        return selected

    @staticmethod
    def _select_awards(
        awards: list[CampaignAwardSnapshot],
        brief: CampaignBrief,
    ) -> tuple[list[CampaignAwardSnapshot], int]:
        available: list[CampaignAwardSnapshot] = []
        for award in awards:
            covers_start = (
                award.available_from is None
                or award.available_from <= brief.start_at
            )
            covers_end = (
                award.available_until is None
                or award.available_until >= brief.end_at
            )
            if award.active and award.inventory > 0 and covers_start and covers_end:
                available.append(award)
        available.sort(
            key=lambda award: (-award.inventory, award.required_points, award.award_id)
        )
        return available[: brief.max_awards], len(awards) - len(available)

    @staticmethod
    def _suggested_task(task: CampaignTaskSnapshot) -> SuggestedCampaignTask:
        return SuggestedCampaignTask(
            task_id=task.task_id,
            task_name=task.task_name,
            max_reward_per_user=task.max_reward_per_user,
            source_ref=task.source_ref,
        )

    @staticmethod
    def _suggested_award(award: CampaignAwardSnapshot) -> SuggestedCampaignAward:
        return SuggestedCampaignAward(
            award_id=award.award_id,
            award_name=award.award_name,
            required_points=award.required_points,
            inventory=award.inventory,
            source_ref=award.source_ref,
        )

    @staticmethod
    def _risk(code: str, severity: str, message: str) -> CampaignRisk:
        return CampaignRisk(code=code, severity=severity, message=message)
