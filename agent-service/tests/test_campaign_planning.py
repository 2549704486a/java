from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from app.campaign_data import StaticCampaignDataProvider
from app.models import (
    CampaignAwardSnapshot,
    CampaignBrief,
    CampaignPlanningSnapshot,
    CampaignSegmentSnapshot,
    CampaignTaskSnapshot,
    HistoricalCampaignMetric,
)
from app.operator_tools import (
    CAMPAIGN_DRAFT,
    CAMPAIGN_READ,
    build_operator_tools,
)
from app.operator_auth import AuthenticatedOperator, OperatorPermissionError
from app.skills.campaign_planning import CampaignPlanningSkill


TZ = timezone(timedelta(hours=8))
NOW = datetime(2026, 8, 22, 12, 0, tzinfo=TZ)
SEGMENT = "近30天未登录且历史积分大于500"


def planning_snapshot(
    *,
    generated_at: datetime | None = None,
    include_metric: bool = True,
) -> CampaignPlanningSnapshot:
    metrics = []
    if include_metric:
        metrics.append(
            HistoricalCampaignMetric(
                metric_name="participation_rate",
                value=0.2,
                sample_size=3000,
                as_of=NOW - timedelta(days=7),
                source_ref="campaign_metrics:recall_30d:v3",
            )
        )
    return CampaignPlanningSnapshot(
        snapshot_id="snapshot-20260822-001",
        generated_at=generated_at or NOW - timedelta(hours=1),
        segment=CampaignSegmentSnapshot(
            segment_key="inactive-30d-points-500",
            description=SEGMENT,
            estimated_users=1000,
            as_of=NOW - timedelta(hours=1),
        ),
        tasks=[
            CampaignTaskSnapshot(
                task_id=1,
                task_name="连续签到",
                reward_points=100,
                source_ref="task_rule:1:v2",
            ),
            CampaignTaskSnapshot(
                task_id=2,
                task_name="浏览指定商品",
                reward_points=80,
                source_ref="task_rule:2:v1",
            ),
            CampaignTaskSnapshot(
                task_id=3,
                task_name="分享活动",
                reward_points=60,
                source_ref="task_rule:3:v1",
            ),
        ],
        awards=[
            CampaignAwardSnapshot(
                award_id=6,
                award_name="智能手环",
                required_points=1000,
                unit_cost_cents=10000,
                inventory=150,
                available_from=NOW - timedelta(days=1),
                available_until=NOW + timedelta(days=30),
                cost_source_ref="award_config:6:unitCostCents",
                source_ref="award_inventory:6:20260822",
            ),
            CampaignAwardSnapshot(
                award_id=8,
                award_name="蓝牙耳机",
                required_points=1500,
                unit_cost_cents=20000,
                inventory=20,
                available_from=NOW - timedelta(days=1),
                available_until=NOW + timedelta(days=30),
                cost_source_ref="award_config:8:unitCostCents",
                source_ref="award_inventory:8:20260822",
            ),
        ],
        historical_metrics=metrics,
    )


def brief(**overrides) -> CampaignBrief:
    values = {
        "objective": "召回长期未活跃用户",
        "target_segment_key": "inactive-30d-points-500",
        "target_segment": SEGMENT,
        "budget_amount_cents": 1600000,
        "points_issuance_cap": 50000,
        "start_at": NOW + timedelta(days=1),
        "end_at": NOW + timedelta(days=7),
    }
    values.update(overrides)
    return CampaignBrief(**values)


class CampaignPlanningSkillTest(unittest.TestCase):
    def setUp(self) -> None:
        self.skill = CampaignPlanningSkill(now_provider=lambda: NOW)

    def test_generates_traceable_non_publishable_draft(self):
        result = self.skill.create_draft(brief(), planning_snapshot())

        self.assertEqual("DRAFT_READY", result.status)
        self.assertEqual(200, result.estimated_participants)
        self.assertEqual(36000, result.estimated_points_issued)
        self.assertEqual(1600000, result.planned_award_cost_cents)
        self.assertEqual([1, 2], [item.task_id for item in result.suggested_tasks])
        self.assertEqual([6, 8], [item.award_id for item in result.suggested_awards])
        self.assertEqual([150, 5], [item.planned_quantity for item in result.suggested_awards])
        self.assertEqual("snapshot-20260822-001", result.source_snapshot_id)
        self.assertTrue(result.editable)
        self.assertTrue(result.review_required)
        self.assertFalse(result.publishable)
        self.assertIn(
            "AWARD_INVENTORY_COVERAGE_LOW",
            [risk.code for risk in result.risks],
        )

    def test_refuses_to_guess_when_historical_rate_is_missing(self):
        result = self.skill.create_draft(
            brief(),
            planning_snapshot(include_metric=False),
        )

        self.assertEqual("NEEDS_DATA", result.status)
        self.assertEqual("PARTICIPATION_RATE_MISSING", result.reason_code)
        self.assertIsNone(result.estimated_points_issued)
        self.assertIsNone(result.planned_award_cost_cents)

    def test_rejects_stale_snapshot(self):
        result = self.skill.create_draft(
            brief(),
            planning_snapshot(generated_at=NOW - timedelta(days=2)),
        )

        self.assertEqual("NEEDS_DATA", result.status)
        self.assertEqual("STALE_PLANNING_SNAPSHOT", result.reason_code)

    def test_reports_constraint_conflict_when_no_task_fits_points_cap(self):
        result = self.skill.create_draft(
            brief(points_issuance_cap=100),
            planning_snapshot(),
        )

        self.assertEqual("CONSTRAINT_CONFLICT", result.status)
        self.assertEqual([], result.suggested_tasks)
        self.assertIn("NO_TASK_FITS_POINTS_CAP", [risk.code for risk in result.risks])

    def test_reports_constraint_conflict_when_money_budget_cannot_buy_award(self):
        result = self.skill.create_draft(
            brief(budget_amount_cents=9999),
            planning_snapshot(),
        )

        self.assertEqual("CONSTRAINT_CONFLICT", result.status)
        self.assertEqual([], result.suggested_awards)
        self.assertIn(
            "NO_AWARD_FITS_AMOUNT_BUDGET",
            [risk.code for risk in result.risks],
        )

    def test_refuses_to_convert_points_when_award_cost_is_missing(self):
        source = planning_snapshot()
        source.awards[0].unit_cost_cents = None

        result = self.skill.create_draft(brief(), source)

        self.assertEqual("NEEDS_DATA", result.status)
        self.assertEqual("AWARD_UNIT_COST_MISSING", result.reason_code)
        self.assertEqual([], result.suggested_awards)

    def test_excludes_task_that_expires_before_campaign_ends(self):
        source = planning_snapshot()
        source.tasks = [
            source.tasks[0].model_copy(
                update={"available_until": NOW + timedelta(days=2)}
            )
        ]

        result = self.skill.create_draft(brief(), source)

        self.assertEqual("CONSTRAINT_CONFLICT", result.status)
        self.assertEqual([], result.suggested_tasks)


class OperatorToolsTest(unittest.TestCase):
    def test_builds_separate_read_only_and_draft_tools(self):
        provider = StaticCampaignDataProvider(
            {"inactive-30d-points-500": planning_snapshot()}
        )
        operator = AuthenticatedOperator(
            operator_id="operator-01",
            permissions=frozenset({CAMPAIGN_READ, CAMPAIGN_DRAFT}),
        )
        tools = build_operator_tools(
            provider,
            operator,
            planning_skill=CampaignPlanningSkill(now_provider=lambda: NOW),
        )

        self.assertEqual(
            {"get_campaign_planning_snapshot", "draft_campaign_plan"},
            {item.name for item in tools},
        )
        draft_tool = next(item for item in tools if item.name == "draft_campaign_plan")
        result = draft_tool.invoke(
            {
                "target_segment_key": "inactive-30d-points-500",
                "objective": "召回长期未活跃用户",
                "budget_amount_cents": 1600000,
                "points_issuance_cap": 50000,
                "start_at": NOW + timedelta(days=1),
                "end_at": NOW + timedelta(days=7),
            }
        )
        self.assertEqual("DRAFT_READY", result["status"])
        self.assertFalse(result["publishable"])

    def test_read_only_operator_cannot_build_draft_tool(self):
        provider = StaticCampaignDataProvider(
            {"inactive-30d-points-500": planning_snapshot()}
        )
        operator = AuthenticatedOperator(
            operator_id="operator-02",
            permissions=frozenset({CAMPAIGN_READ}),
        )

        tools = build_operator_tools(provider, operator)

        self.assertEqual(
            ["get_campaign_planning_snapshot"],
            [item.name for item in tools],
        )

    def test_rejects_operator_without_read_permission(self):
        provider = StaticCampaignDataProvider(
            {"inactive-30d-points-500": planning_snapshot()}
        )
        operator = AuthenticatedOperator(
            operator_id="operator-03",
            permissions=frozenset({CAMPAIGN_DRAFT}),
        )

        with self.assertRaises(OperatorPermissionError):
            build_operator_tools(provider, operator)


if __name__ == "__main__":
    unittest.main()
