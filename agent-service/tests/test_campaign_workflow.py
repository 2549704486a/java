from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.auth import JwtAuthenticator
from app.campaign_data import StaticCampaignDataProvider
from app.models import (
    CampaignAwardSnapshot,
    CampaignPlanningSnapshot,
    CampaignSegmentSnapshot,
    CampaignTaskSnapshot,
    HistoricalCampaignMetric,
    ToolEnvelope,
)
from app.operator_auth import AuthenticatedOperator, OperatorAuthenticator
from app.operator_tools import (
    CAMPAIGN_DRAFT,
    CAMPAIGN_METRIC,
    CAMPAIGN_PUBLISH,
    CAMPAIGN_READ,
    CAMPAIGN_REVIEW,
    build_operator_tools,
)
from app.web import create_app


TZ = timezone(timedelta(hours=8))
NOW = datetime.now(TZ).replace(microsecond=0)
PERMISSIONS = frozenset(
    {
        CAMPAIGN_READ,
        CAMPAIGN_DRAFT,
        CAMPAIGN_REVIEW,
        CAMPAIGN_PUBLISH,
        CAMPAIGN_METRIC,
    }
)


def planning_snapshot() -> CampaignPlanningSnapshot:
    return CampaignPlanningSnapshot(
        snapshot_id="workflow-snapshot",
        generated_at=NOW,
        segment=CampaignSegmentSnapshot(
            segment_key="POINTS_AT_LEAST_500",
            description="积分不少于 500 的用户",
            estimated_users=120,
            as_of=NOW,
        ),
        tasks=[
            CampaignTaskSnapshot(
                task_id=1,
                task_name="每日签到",
                reward_points=20,
                source_ref="task_config:1",
            )
        ],
        awards=[
            CampaignAwardSnapshot(
                award_id=6,
                award_name="智能手表",
                required_points=5000,
                unit_cost_cents=19900,
                inventory=100,
                available_from=NOW,
                available_until=NOW + timedelta(days=30),
                cost_source_ref="award_config:6:unitCostCents",
                source_ref="award_config:6",
            )
        ],
        historical_metrics=[
            HistoricalCampaignMetric(
                metric_name="participation_rate",
                value=0.25,
                sample_size=1000,
                as_of=NOW,
                source_ref="campaign_metric_history:1",
            )
        ],
    )


class FakeWorkflowClient:
    def __init__(self) -> None:
        self.created_payload: dict | None = None
        self.action_calls: list[tuple[int, str, dict]] = []
        self.metric_calls: list[tuple[int, dict]] = []

    def create_campaign_draft(self, payload: dict) -> ToolEnvelope:
        self.created_payload = payload
        return ToolEnvelope(
            success=True,
            code="CAMPAIGN_DRAFT_CREATED",
            data={"id": 1, "version": 1, "status": "DRAFT"},
            message="created",
            retryable=False,
        )

    def list_campaign_drafts(self, limit: int = 50) -> ToolEnvelope:
        return ToolEnvelope(
            success=True,
            code="CAMPAIGN_DRAFTS_FOUND",
            data=[],
            message="ok",
            retryable=False,
        )

    def act_on_campaign_draft(
        self, draft_id: int, action: str, payload: dict
    ) -> ToolEnvelope:
        self.action_calls.append((draft_id, action, payload))
        return ToolEnvelope(
            success=True,
            code="CAMPAIGN_DRAFT_UPDATED",
            data={"id": draft_id, "version": payload["version"] + 1},
            message="ok",
            retryable=False,
        )

    def list_campaign_activities(self, limit: int = 50) -> ToolEnvelope:
        return ToolEnvelope(
            success=True,
            code="CAMPAIGN_ACTIVITIES_FOUND",
            data=[],
            message="ok",
            retryable=False,
        )

    def record_campaign_metric(self, activity_id: int, payload: dict) -> ToolEnvelope:
        self.metric_calls.append((activity_id, payload))
        return ToolEnvelope(
            success=True,
            code="CAMPAIGN_METRIC_RECORDED",
            data={"activityId": activity_id},
            message="ok",
            retryable=False,
        )

    def list_campaign_metrics(self, activity_id: int) -> ToolEnvelope:
        return ToolEnvelope(
            success=True,
            code="CAMPAIGN_METRICS_FOUND",
            data=[],
            message="ok",
            retryable=False,
        )


class FakeRuntime:
    def __init__(self, client: FakeWorkflowClient) -> None:
        self.client = client
        self.operator_knowledge_search = None

    def health(self) -> dict:
        return {"status": "UP"}

    def close(self) -> None:
        pass


class CampaignWorkflowTest(unittest.TestCase):
    def test_agent_draft_tool_persists_generated_plan(self):
        client = FakeWorkflowClient()
        provider = StaticCampaignDataProvider(
            {"POINTS_AT_LEAST_500": planning_snapshot()}
        )
        operator = AuthenticatedOperator("operator-01", PERMISSIONS)
        tool = next(
            item
            for item in build_operator_tools(
                provider,
                operator,
                business_client=client,
            )
            if item.name == "draft_campaign_plan"
        )

        result = tool.invoke(
            {
                "target_segment_key": "POINTS_AT_LEAST_500",
                "objective": "提高任务参与率",
                "budget_amount_cents": 100000,
                "points_issuance_cap": 5000,
                "start_at": NOW + timedelta(days=1),
                "end_at": NOW + timedelta(days=7),
                "max_tasks": 1,
                "max_awards": 1,
            }
        )

        self.assertEqual("CAMPAIGN_DRAFT_CREATED", result["code"])
        self.assertEqual("operator-01", client.created_payload["operatorId"])
        self.assertIn("DRAFT_READY", client.created_payload["planJson"])

    def test_http_workflow_binds_operator_identity(self):
        workflow_client = FakeWorkflowClient()
        runtime = FakeRuntime(workflow_client)
        provider = StaticCampaignDataProvider(
            {"POINTS_AT_LEAST_500": planning_snapshot()}
        )
        authenticator = JwtAuthenticator(
            "workflow-user-secret-that-is-longer-than-32-characters",
            "test-agent",
            "test-web",
        )
        application = create_app(
            lambda: runtime,
            lambda: authenticator,
            lambda: OperatorAuthenticator(
                "operator-token", "reviewer-01", PERMISSIONS
            ),
            lambda ignored_runtime: provider,
            lambda ignored_runtime, ignored_provider: None,
        )
        headers = {"Authorization": "Bearer operator-token"}

        with TestClient(application) as http:
            submitted = http.post(
                "/v1/operator/campaign/drafts/7/submit",
                headers=headers,
                json={"version": 2, "comment": "ready"},
            )
            metric = http.post(
                "/v1/operator/campaign/activities/9/metrics",
                headers=headers,
                json={
                    "metric_name": "participation_rate",
                    "metric_value": 0.31,
                    "sample_size": 1200,
                    "measured_at": NOW.isoformat(),
                    "source_ref": "campaign-report-9",
                },
            )

        self.assertEqual(200, submitted.status_code)
        self.assertEqual((7, "submit"), workflow_client.action_calls[0][:2])
        self.assertEqual(
            "reviewer-01", workflow_client.action_calls[0][2]["operatorId"]
        )
        self.assertEqual(200, metric.status_code)
        self.assertEqual(
            "reviewer-01", workflow_client.metric_calls[0][1]["operatorId"]
        )


if __name__ == "__main__":
    unittest.main()
