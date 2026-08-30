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

        if snapshot.segment.segment_key != brief.target_segment_key:
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
                estimated_points_issued=0,
                planned_award_cost_cents=0,
                risks=[
                    self._risk(
                        "ZERO_EXPECTED_PARTICIPATION",
                        "BLOCKING",
                        "当前活动目标和用户群缺少可预期的参与者",
                    )
                ],
                **base,
            )

        available_awards, excluded_awards = self._available_awards(
            snapshot.awards,
            brief,
        )
        missing_cost_awards = [
            award for award in available_awards if award.unit_cost_cents is None
        ]
        if missing_cost_awards:
            missing_ids = ", ".join(str(award.award_id) for award in missing_cost_awards)
            return CampaignPlanDraft(
                status="NEEDS_DATA",
                reason_code="AWARD_UNIT_COST_MISSING",
                message="候选奖品缺少真实单位成本，不能生成金额预算草案",
                risks=[
                    self._risk(
                        "AWARD_UNIT_COST_MISSING",
                        "BLOCKING",
                        f"奖品 {missing_ids} 需要由采购或运营数据回填单位成本",
                    )
                ],
                **base,
            )

        per_user_points_cap = brief.points_issuance_cap // estimated_participants
        tasks = self._select_tasks(
            snapshot.tasks,
            brief.max_tasks,
            per_user_points_cap,
            brief,
        )
        award_plans = self._plan_awards(
            available_awards,
            brief,
            estimated_participants,
        )

        risks: list[CampaignRisk] = []
        if not tasks:
            risks.append(
                self._risk(
                    "NO_TASK_FITS_POINTS_CAP",
                    "BLOCKING",
                    "现有任务奖励无法放入当前人均积分发放上限",
                )
            )
        if not award_plans:
            code = (
                "NO_AWARD_FITS_AMOUNT_BUDGET"
                if available_awards
                else "NO_AWARD_AVAILABLE_FOR_WINDOW"
            )
            message = (
                "金额预算不足以配置任何候选奖品"
                if available_awards
                else "没有库存充足且覆盖活动时间窗口的奖品"
            )
            risks.append(
                self._risk(
                    code,
                    "BLOCKING",
                    message,
                )
            )

        estimated_points_issued = estimated_participants * sum(
            task.max_reward_per_user for task in tasks
        )
        planned_award_cost_cents = sum(
            quantity * award.unit_cost_cents
            for award, quantity in award_plans
            if award.unit_cost_cents is not None
        )
        if tasks and estimated_points_issued < brief.points_issuance_cap * 0.5:
            risks.append(
                self._risk(
                    "LOW_POINTS_CAP_UTILIZATION",
                    "WARNING",
                    "当前任务组合预计使用不到一半积分发放上限，可由运营人员调整",
                )
            )
        if award_plans and planned_award_cost_cents < brief.budget_amount_cents * 0.5:
            risks.append(
                self._risk(
                    "LOW_AMOUNT_BUDGET_UTILIZATION",
                    "WARNING",
                    "当前奖品计划使用不到一半金额预算，可由运营人员调整",
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
        if award_plans:
            planned_quantity = sum(quantity for _, quantity in award_plans)
            if planned_quantity < estimated_participants:
                risks.append(
                    self._risk(
                        "AWARD_INVENTORY_COVERAGE_LOW",
                        "WARNING",
                        "金额预算和库存下的奖品计划仅覆盖预计参与人数的 "
                        f"{planned_quantity}/{estimated_participants}",
                    )
                )
            risks.append(
                self._risk(
                    "AWARD_RELEVANCE_REVIEW_REQUIRED",
                    "INFO",
                    "当前仅按可用性和库存选择奖品，仍需人工审核奖品与活动目标的匹配度",
                )
            )
            risks.append(
                self._risk(
                    "AWARD_QUANTITY_ASSUMPTION_REVIEW_REQUIRED",
                    "INFO",
                    "当前按每位预计参与者最多一个奖品名额规划数量，发布前需核对活动规则",
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
            estimated_points_issued=estimated_points_issued,
            planned_award_cost_cents=planned_award_cost_cents,
            suggested_tasks=[self._suggested_task(task) for task in tasks],
            suggested_awards=[
                self._suggested_award(award, quantity)
                for award, quantity in award_plans
            ],
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
            "target_segment_key": brief.target_segment_key,
            "target_segment": brief.target_segment,
            "budget_amount_cents": brief.budget_amount_cents,
            "points_issuance_cap": brief.points_issuance_cap,
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
        per_user_points_cap: int,
        brief: CampaignBrief,
    ) -> list[CampaignTaskSnapshot]:
        selected: list[CampaignTaskSnapshot] = []
        remaining = per_user_points_cap
        candidates = sorted(
            (
                task
                for task in tasks
                if task.active
                and (
                    task.available_from is None
                    or task.available_from <= brief.start_at
                )
                and (
                    task.available_until is None
                    or task.available_until >= brief.end_at
                )
            ),
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
    def _available_awards(
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
        return available, len(awards) - len(available)

    @staticmethod
    def _plan_awards(
        awards: list[CampaignAwardSnapshot],
        brief: CampaignBrief,
        estimated_participants: int,
    ) -> list[tuple[CampaignAwardSnapshot, int]]:
        """在金额预算内规划奖品数量；不使用兑换积分换算成本。"""

        planned: list[tuple[CampaignAwardSnapshot, int]] = []
        remaining_budget = brief.budget_amount_cents
        remaining_quantity = estimated_participants
        candidates = sorted(
            awards,
            key=lambda award: (
                award.unit_cost_cents if award.unit_cost_cents is not None else math.inf,
                -award.inventory,
                award.required_points,
                award.award_id,
            ),
        )
        for award in candidates:
            if len(planned) >= brief.max_awards or remaining_quantity <= 0:
                break
            if award.unit_cost_cents is None:
                continue
            affordable_quantity = (
                remaining_quantity
                if award.unit_cost_cents == 0
                else remaining_budget // award.unit_cost_cents
            )
            quantity = min(award.inventory, remaining_quantity, affordable_quantity)
            if quantity <= 0:
                continue
            planned.append((award, quantity))
            remaining_quantity -= quantity
            remaining_budget -= quantity * award.unit_cost_cents
        return planned

    @staticmethod
    def _suggested_task(task: CampaignTaskSnapshot) -> SuggestedCampaignTask:
        return SuggestedCampaignTask(
            task_id=task.task_id,
            task_name=task.task_name,
            max_reward_per_user=task.max_reward_per_user,
            source_ref=task.source_ref,
        )

    @staticmethod
    def _suggested_award(
        award: CampaignAwardSnapshot,
        planned_quantity: int,
    ) -> SuggestedCampaignAward:
        if award.unit_cost_cents is None:
            raise ValueError("奖品单位成本缺失")
        return SuggestedCampaignAward(
            award_id=award.award_id,
            award_name=award.award_name,
            required_points=award.required_points,
            unit_cost_cents=award.unit_cost_cents,
            inventory=award.inventory,
            planned_quantity=planned_quantity,
            planned_cost_cents=planned_quantity * award.unit_cost_cents,
            cost_source_ref=award.cost_source_ref,
            source_ref=award.source_ref,
        )

    @staticmethod
    def _risk(code: str, severity: str, message: str) -> CampaignRisk:
        return CampaignRisk(code=code, severity=severity, message=message)
