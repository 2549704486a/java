from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

import httpx
from fastapi.testclient import TestClient

from app.api_client import BusinessApiClient
from app.auth import JwtAuthenticator
from app.campaign_data import HttpCampaignDataProvider, StaticCampaignDataProvider
from app.models import (
    CampaignAwardSnapshot,
    CampaignPlanningSnapshot,
    CampaignSegmentSnapshot,
    CampaignTaskSnapshot,
    HistoricalCampaignMetric,
)
from app.operator_auth import OperatorAuthenticator
from app.operator_tools import CAMPAIGN_DRAFT, CAMPAIGN_READ
from app.web import create_app


TZ = timezone(timedelta(hours=8))
NOW = datetime.now(TZ).replace(microsecond=0)
SEGMENT_KEY = "POINTS_AT_LEAST_500"
USER_AUTHENTICATOR = JwtAuthenticator(
    "operator-api-user-secret-that-is-longer-than-32-characters",
    "test-agent",
    "test-web",
)


class FakeRuntime:
    def __init__(self) -> None:
        self.client = object()

    def health(self) -> dict:
        return {"status": "UP"}

    def close(self) -> None:
        pass


def snapshot() -> CampaignPlanningSnapshot:
    return CampaignPlanningSnapshot(
        snapshot_id="snapshot-001",
        generated_at=NOW,
        segment=CampaignSegmentSnapshot(
            segment_key=SEGMENT_KEY,
            description="当前积分不少于 500 的用户",
            estimated_users=100,
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
                inventory=20,
                available_from=NOW - timedelta(days=1),
                available_until=NOW + timedelta(days=30),
                source_ref="award_config:6",
            )
        ],
        historical_metrics=[
            HistoricalCampaignMetric(
                metric_name="participation_rate",
                value=0.2,
                sample_size=100,
                as_of=NOW,
                source_ref="campaign_metric_history:1",
            )
        ],
    )


def create_operator_app(permissions: frozenset[str]):
    provider = StaticCampaignDataProvider({SEGMENT_KEY: snapshot()})
    return create_app(
        lambda: FakeRuntime(),
        lambda: USER_AUTHENTICATOR,
        lambda: OperatorAuthenticator("operator-token", "operator-01", permissions),
        lambda runtime: provider,
    )


class OperatorApiTest(unittest.TestCase):
    def test_operator_snapshot_uses_separate_token(self):
        app = create_operator_app(frozenset({CAMPAIGN_READ}))
        user_token = USER_AUTHENTICATOR.issue_token(10, 60)

        with TestClient(app) as client:
            rejected = client.get(
                f"/v1/operator/campaign/snapshots/{SEGMENT_KEY}",
                headers={"Authorization": f"Bearer {user_token}"},
            )
            accepted = client.get(
                f"/v1/operator/campaign/snapshots/{SEGMENT_KEY}",
                headers={
                    "Authorization": "Bearer operator-token",
                    "X-Request-ID": "operator-snapshot-001",
                },
            )

        self.assertEqual(401, rejected.status_code)
        self.assertEqual("INVALID_OPERATOR_TOKEN", rejected.json()["code"])
        self.assertEqual(200, accepted.status_code)
        self.assertEqual("CAMPAIGN_SNAPSHOT_FOUND", accepted.json()["code"])
        self.assertEqual(
            SEGMENT_KEY,
            accepted.json()["data"]["segment"]["segment_key"],
        )

    def test_draft_requires_server_side_permission(self):
        app = create_operator_app(frozenset({CAMPAIGN_READ}))

        with TestClient(app) as client:
            response = client.post(
                "/v1/operator/campaign/drafts",
                headers={"Authorization": "Bearer operator-token"},
                json={
                    "target_segment_key": SEGMENT_KEY,
                    "objective": "提高积分任务参与率",
                    "budget_points": 5000,
                    "start_at": (NOW + timedelta(days=1)).isoformat(),
                    "end_at": (NOW + timedelta(days=7)).isoformat(),
                },
            )

        self.assertEqual(403, response.status_code)
        self.assertEqual("OPERATOR_PERMISSION_DENIED", response.json()["code"])

    def test_authorized_operator_can_create_non_publishable_draft(self):
        app = create_operator_app(frozenset({CAMPAIGN_READ, CAMPAIGN_DRAFT}))

        with TestClient(app) as client:
            response = client.post(
                "/v1/operator/campaign/drafts",
                headers={"Authorization": "Bearer operator-token"},
                json={
                    "target_segment_key": SEGMENT_KEY,
                    "objective": "提高积分任务参与率",
                    "budget_points": 5000,
                    "start_at": (NOW + timedelta(days=1)).isoformat(),
                    "end_at": (NOW + timedelta(days=7)).isoformat(),
                },
            )

        self.assertEqual(200, response.status_code)
        self.assertEqual("DRAFT_READY", response.json()["status"])
        self.assertEqual(SEGMENT_KEY, response.json()["target_segment_key"])
        self.assertFalse(response.json()["publishable"])


class HttpCampaignDataProviderTest(unittest.TestCase):
    def test_validates_java_camel_case_snapshot(self):
        payload = snapshot().model_dump(mode="json", by_alias=True)

        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(
                f"/agent/operator/query/campaign-planning/snapshots/{SEGMENT_KEY}",
                request.url.path,
            )
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "code": "CAMPAIGN_SNAPSHOT_FOUND",
                    "data": payload,
                    "message": "ok",
                    "retryable": False,
                },
            )

        http_client = httpx.Client(
            base_url="http://business.test",
            transport=httpx.MockTransport(handler),
        )
        business_client = BusinessApiClient(
            "http://business.test",
            client=http_client,
        )

        result = HttpCampaignDataProvider(business_client).get_planning_snapshot(
            SEGMENT_KEY
        )

        self.assertEqual(SEGMENT_KEY, result.segment.segment_key)
        self.assertEqual(20, result.awards[0].inventory)
        http_client.close()


if __name__ == "__main__":
    unittest.main()
