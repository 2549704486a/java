from __future__ import annotations

import unittest
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.auth import JwtAuthenticator
from app.observability.models import (
    AGENT_OBSERVE_PERMISSION,
    AgentRequestDetail,
    AgentRequestPage,
    AgentRequestRecord,
    AgentToolObservation,
)
from app.observability.service import AgentObservabilityService
from app.operator.auth import OperatorAuthenticator
from app.operator.tools import CAMPAIGN_READ
from app.web import create_app


USER_AUTHENTICATOR = JwtAuthenticator(
    "observability-api-user-secret-that-is-longer-than-32-characters",
    "test-agent",
    "test-web",
)


class FakeRuntime:
    def __init__(self) -> None:
        self.client = object()
        self.operator_knowledge_search = None

    async def initialize(self) -> None:
        return None

    def health(self) -> dict:
        return {"status": "UP"}

    def close(self) -> None:
        return None


class FakeObservationStore:
    def __init__(self) -> None:
        now = datetime.now(timezone.utc)
        self.record = AgentRequestRecord(
            request_id="observed-request-001",
            agent_type="USER",
            started_at=now,
            completed_at=now,
            status="COMPLETED",
            elapsed_ms=120,
            model_call_count=1,
            input_tokens=20,
            output_tokens=8,
            tool_call_count=1,
            error_type=None,
        )
        self.tool = AgentToolObservation(
            request_id=self.record.request_id,
            sequence=1,
            tool_name="get_user_points",
            transport="REST",
            completed=True,
            business_success=True,
            result_code="POINTS_FOUND",
            elapsed_ms=15,
            error_type=None,
        )
        self.list_arguments = None

    def scan_requests(self, started_at, ended_at):
        return [self.record]

    def scan_tools(self, request_ids):
        return [self.tool] if self.record.request_id in request_ids else []

    def list_requests(self, **kwargs):
        self.list_arguments = kwargs
        return AgentRequestPage(
            total=1,
            page=kwargs["page"],
            page_size=kwargs["page_size"],
            items=(self.record,),
        )

    def get_request(self, request_id):
        if request_id != self.record.request_id:
            return None
        return AgentRequestDetail(request=self.record, tool_calls=(self.tool,))


def create_observation_app(permissions: frozenset[str]):
    return create_app(
        lambda: FakeRuntime(),
        lambda: USER_AUTHENTICATOR,
        lambda: OperatorAuthenticator(
            "operator-token",
            "operator-observer",
            permissions,
        ),
    )


class AgentObservabilityApiTest(unittest.TestCase):
    def test_requires_operator_token_and_dedicated_permission(self):
        app = create_observation_app(frozenset({CAMPAIGN_READ}))

        with TestClient(app) as client:
            no_token = client.get("/v1/operator/agent-observability/summary")
            forbidden = client.get(
                "/v1/operator/agent-observability/requests/not-visible",
                headers={"Authorization": "Bearer operator-token"},
            )

        self.assertEqual(401, no_token.status_code)
        self.assertEqual(403, forbidden.status_code)
        self.assertNotIn("NOT_FOUND", forbidden.text)

    def test_returns_summary_filtered_page_and_detail(self):
        store = FakeObservationStore()
        app = create_observation_app(
            frozenset({CAMPAIGN_READ, AGENT_OBSERVE_PERMISSION})
        )
        headers = {
            "Authorization": "Bearer operator-token",
            "X-Request-ID": "observe-api-001",
        }

        with TestClient(app) as client:
            app.state.agent_observability_service = AgentObservabilityService(store)
            summary = client.get(
                "/v1/operator/agent-observability/summary?window=24h",
                headers=headers,
            )
            page = client.get(
                "/v1/operator/agent-observability/requests"
                "?window=7d&agent_type=USER&status=COMPLETED&page=2&page_size=5",
                headers=headers,
            )
            detail = client.get(
                "/v1/operator/agent-observability/requests/observed-request-001",
                headers=headers,
            )

        self.assertEqual(200, summary.status_code)
        self.assertEqual(1, summary.json()["requests"]["total"])
        self.assertEqual("observe-api-001", summary.headers["X-Request-ID"])
        self.assertEqual(200, page.status_code)
        self.assertEqual("USER", store.list_arguments["agent_type"])
        self.assertEqual("COMPLETED", store.list_arguments["status"])
        self.assertEqual(2, store.list_arguments["page"])
        self.assertEqual(200, detail.status_code)
        self.assertEqual(
            "get_user_points",
            detail.json()["tool_calls"][0]["tool_name"],
        )

    def test_rejects_invalid_filters_and_reports_missing_request(self):
        store = FakeObservationStore()
        app = create_observation_app(frozenset({AGENT_OBSERVE_PERMISSION}))
        headers = {"Authorization": "Bearer operator-token"}

        with TestClient(app) as client:
            app.state.agent_observability_service = AgentObservabilityService(store)
            invalid_window = client.get(
                "/v1/operator/agent-observability/summary?window=90d",
                headers=headers,
            )
            invalid_filter = client.get(
                "/v1/operator/agent-observability/requests?agent_type=UNKNOWN",
                headers=headers,
            )
            invalid_page_size = client.get(
                "/v1/operator/agent-observability/requests?page_size=101",
                headers=headers,
            )
            missing = client.get(
                "/v1/operator/agent-observability/requests/missing-request",
                headers=headers,
            )

        self.assertEqual(422, invalid_window.status_code)
        self.assertEqual(422, invalid_filter.status_code)
        self.assertEqual(422, invalid_page_size.status_code)
        self.assertEqual(404, missing.status_code)
        self.assertEqual("AGENT_OBSERVATION_NOT_FOUND", missing.json()["code"])

    def test_reports_feature_unavailable_without_store(self):
        app = create_observation_app(frozenset({AGENT_OBSERVE_PERMISSION}))

        with TestClient(app) as client:
            response = client.get(
                "/v1/operator/agent-observability/summary",
                headers={"Authorization": "Bearer operator-token"},
            )

        self.assertEqual(503, response.status_code)
        self.assertEqual("AGENT_OBSERVABILITY_UNAVAILABLE", response.json()["code"])


if __name__ == "__main__":
    unittest.main()
