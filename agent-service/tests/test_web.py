from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.auth import JwtAuthenticator
from app.models import PendingExchangeData, ToolEnvelope
from app.web import create_app


TEST_AUTHENTICATOR = JwtAuthenticator(
    "web-test-auth-secret-that-is-longer-than-32-characters",
    "test-agent",
    "test-web",
)


def auth_headers(user_id: int = 10, request_id: str | None = None) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {TEST_AUTHENTICATOR.issue_token(user_id, 60)}"
    }
    if request_id:
        headers["X-Request-ID"] = request_id
    return headers


def create_test_app(runtime: "FakeRuntime"):
    return create_app(lambda: runtime, lambda: TEST_AUTHENTICATOR)


class FakeBusinessClient:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []

    def get_user_points(self, user_id: int) -> ToolEnvelope:
        self.calls.append(("points", user_id))
        return ToolEnvelope(
            success=True,
            code="POINTS_FOUND",
            data={"userId": user_id, "points": 680},
            message="积分查询成功",
        )

    def list_awards(self, user_id: int) -> ToolEnvelope:
        self.calls.append(("awards", user_id))
        return ToolEnvelope(
            success=True,
            code="AWARDS_FOUND",
            data=[
                {
                    "award": {
                        "awardId": 6,
                        "name": "城市随行保温杯",
                        "coverUrl": None,
                        "awardType": 1,
                        "inventory": 100,
                        "requiredPoints": 500,
                        "startTime": "2026-01-01T00:00:00",
                        "endTime": "2027-01-01T00:00:00",
                        "overSellAllowed": False,
                    },
                    "redeemable": True,
                    "pointsGap": 0,
                    "reasonCode": "ELIGIBLE",
                }
            ],
            message="奖品列表查询成功",
        )

    def list_exchange_records(self, user_id: int) -> ToolEnvelope:
        self.calls.append(("orders", user_id))
        return ToolEnvelope(
            success=True,
            code="EXCHANGE_RECORDS_FOUND",
            data=[
                {
                    "orderId": 101,
                    "awardId": 6,
                    "awardName": "城市随行保温杯",
                    "status": "PROCESSING",
                    "statusMessage": "兑换正在处理中",
                    "createTime": "2026-08-24T10:00:00",
                    "updateTime": "2026-08-24T10:00:01",
                }
            ],
            message="兑换记录查询成功",
        )

    def list_notifications(self, user_id: int) -> ToolEnvelope:
        self.calls.append(("notifications", user_id))
        return ToolEnvelope(
            success=True,
            code="NOTIFICATIONS_FOUND",
            data=[
                {
                    "id": 201,
                    "activityId": 31,
                    "title": "积分加速活动",
                    "content": "完成签到任务可获得额外积分。",
                    "status": "UNREAD",
                    "readAt": None,
                    "clickedAt": None,
                    "createdAt": "2026-08-25T10:00:00",
                }
            ],
            message="站内消息查询成功",
        )

    def mark_notification_read(self, user_id: int, notification_id: int) -> ToolEnvelope:
        self.calls.append(("notification_read", user_id, notification_id))
        return self._notification_action(notification_id, "READ")

    def mark_notification_clicked(self, user_id: int, notification_id: int) -> ToolEnvelope:
        self.calls.append(("notification_click", user_id, notification_id))
        return self._notification_action(notification_id, "CLICKED")

    @staticmethod
    def _notification_action(notification_id: int, status: str) -> ToolEnvelope:
        return ToolEnvelope(
            success=True,
            code="NOTIFICATION_UPDATED",
            data={
                "id": notification_id,
                "activityId": 31,
                "title": "积分加速活动",
                "content": "完成签到任务可获得额外积分。",
                "status": status,
                "readAt": "2026-08-25T10:05:00",
                "clickedAt": (
                    "2026-08-25T10:06:00" if status == "CLICKED" else None
                ),
                "createdAt": "2026-08-25T10:00:00",
            },
            message="站内消息状态更新成功",
        )


class FakeRuntime:
    def __init__(
        self,
        should_fail: bool = False,
        pending=None,
    ) -> None:
        self.should_fail = should_fail
        self.pending = pending
        self.closed = False
        self.calls: list[tuple[int, str, str, str | None]] = []
        self.client = FakeBusinessClient()

    def health(self):
        return {
            "status": "UP",
            "model": "test-model",
            "cached_agents": 0,
            "agent_cache_size": 2,
            "cached_sessions": 0,
            "session_cache_size": 2,
            "skills": [],
        }

    def answer(
        self,
        user_id: int,
        session_id: str,
        message: str,
        request_id: str | None = None,
    ):
        self.calls.append((user_id, session_id, message, request_id))
        if self.should_fail:
            raise RuntimeError("不应返回给调用方的内部异常")
        return "测试回答", 12.345

    def close(self) -> None:
        self.closed = True

    def pending_exchange(self, user_id: int, session_id: str):
        return self.pending

class AgentWebTest(unittest.TestCase):
    def test_operator_deep_link_returns_spa_entry(self):
        runtime = FakeRuntime()
        with TemporaryDirectory() as temp_dir:
            frontend_dist = Path(temp_dir)
            frontend_dist.joinpath("index.html").write_text(
                "<html><body>operator-spa</body></html>",
                encoding="utf-8",
            )
            with patch("app.web.FRONTEND_DIST", frontend_dist):
                app = create_test_app(runtime)
                with TestClient(app) as client:
                    response = client.get("/operator")

        self.assertEqual(200, response.status_code)
        self.assertIn("operator-spa", response.text)
        self.assertIn("text/html", response.headers["content-type"])

    def test_chat_returns_safe_pending_exchange_without_confirmation_token(self):
        runtime = FakeRuntime(
            pending=PendingExchangeData(
                status="AWAITING_CONFIRMATION",
                awardId=6,
                awardName="手表",
                currentPoints=300,
                requiredPoints=200,
                remainingPoints=100,
                expiresAt="2026-08-21T08:02:00Z",
            )
        )
        app = create_test_app(runtime)

        with TestClient(app) as client:
            response = client.post(
                "/v1/chat",
                headers=auth_headers(),
                json={
                    "session_id": "session-001",
                    "message": "兑换6号奖品",
                },
            )

        pending = response.json()["pending_exchange"]
        self.assertEqual("手表", pending["awardName"])
        self.assertEqual(100, pending["remainingPoints"])
        self.assertNotIn("confirmationId", pending)

    def test_dashboard_aggregates_points_and_awards(self):
        runtime = FakeRuntime()
        app = create_test_app(runtime)

        with TestClient(app) as client:
            response = client.get(
                "/v1/dashboard",
                headers=auth_headers(request_id="dashboard-001"),
            )

        self.assertEqual(200, response.status_code)
        self.assertEqual("dashboard-001", response.headers["X-Request-ID"])
        self.assertEqual(680, response.json()["points"])
        self.assertEqual("城市随行保温杯", response.json()["awards"][0]["award"]["name"])
        self.assertEqual(
            [("points", 10), ("awards", 10)],
            runtime.client.calls,
        )

    def test_orders_use_authenticated_user_and_return_persisted_status(self):
        runtime = FakeRuntime()
        app = create_test_app(runtime)

        with TestClient(app) as client:
            response = client.get(
                "/v1/orders",
                headers=auth_headers(user_id=11, request_id="orders-001"),
            )

        self.assertEqual(200, response.status_code)
        self.assertEqual("orders-001", response.headers["X-Request-ID"])
        self.assertEqual(11, response.json()["user_id"])
        self.assertEqual("PROCESSING", response.json()["records"][0]["status"])
        self.assertEqual([("orders", 11)], runtime.client.calls)

    def test_notifications_use_authenticated_user(self):
        runtime = FakeRuntime()
        app = create_test_app(runtime)

        with TestClient(app) as client:
            response = client.get(
                "/v1/notifications",
                headers=auth_headers(user_id=12, request_id="notifications-001"),
            )

        self.assertEqual(200, response.status_code)
        self.assertEqual("notifications-001", response.headers["X-Request-ID"])
        self.assertEqual(12, response.json()["user_id"])
        self.assertEqual("UNREAD", response.json()["notifications"][0]["status"])
        self.assertEqual([("notifications", 12)], runtime.client.calls)

    def test_notification_action_is_bound_to_authenticated_user(self):
        runtime = FakeRuntime()
        app = create_test_app(runtime)

        with TestClient(app) as client:
            read_response = client.post(
                "/v1/notifications/201/read",
                headers=auth_headers(user_id=13),
            )
            click_response = client.post(
                "/v1/notifications/201/click",
                headers=auth_headers(user_id=13),
            )

        self.assertEqual(200, read_response.status_code)
        self.assertEqual("READ", read_response.json()["notification"]["status"])
        self.assertEqual(200, click_response.status_code)
        self.assertEqual("CLICKED", click_response.json()["notification"]["status"])
        self.assertEqual(
            [
                ("notification_read", 13, 201),
                ("notification_click", 13, 201),
            ],
            runtime.client.calls,
        )

    def test_health_and_chat_contract(self):
        runtime = FakeRuntime()
        app = create_test_app(runtime)

        with TestClient(app) as client:
            health = client.get("/health")
            response = client.post(
                "/v1/chat",
                headers=auth_headers(request_id="request-001"),
                json={
                    "session_id": "session-001",
                    "message": "  我有多少积分？  ",
                },
            )

        self.assertEqual(200, health.status_code)
        self.assertEqual("UP", health.json()["status"])
        self.assertEqual(200, response.status_code)
        self.assertEqual("request-001", response.headers["X-Request-ID"])
        self.assertEqual(
            {
                "request_id": "request-001",
                "session_id": "session-001",
                "user_id": 10,
                "answer": "测试回答",
                "elapsed_ms": 12.35,
                "pending_exchange": None,
            },
            response.json(),
        )
        self.assertEqual(
            [(10, "session-001", "我有多少积分？", "request-001")],
            runtime.calls,
        )
        self.assertTrue(runtime.closed)

    def test_rejects_invalid_request_before_runtime_call(self):
        runtime = FakeRuntime()
        app = create_test_app(runtime)

        with TestClient(app) as client:
            injected_user = client.post(
                "/v1/chat",
                headers=auth_headers(),
                json={"user_id": 11, "message": "查询积分"},
            )
            blank_message = client.post(
                "/v1/chat", headers=auth_headers(), json={"message": "   "}
            )
            invalid_session = client.post(
                "/v1/chat",
                headers=auth_headers(),
                json={
                    "session_id": "invalid session",
                    "message": "查询积分",
                },
            )

        self.assertEqual(422, injected_user.status_code)
        self.assertEqual(422, blank_message.status_code)
        self.assertEqual(422, invalid_session.status_code)
        self.assertEqual([], runtime.calls)

    def test_returns_sanitized_error_and_generated_request_id(self):
        runtime = FakeRuntime(should_fail=True)
        app = create_test_app(runtime)

        with TestClient(app) as client:
            with self.assertLogs("app.web", level="ERROR"):
                response = client.post(
                    "/v1/chat",
                    headers={
                        **auth_headers(),
                        "X-Request-ID": "invalid request id",
                    },
                    json={"message": "查询积分"},
                )

        body = response.json()
        self.assertEqual(503, response.status_code)
        self.assertEqual("AGENT_SERVICE_UNAVAILABLE", body["code"])
        self.assertNotIn("内部异常", body["message"])
        self.assertEqual(32, len(body["request_id"]))
        self.assertEqual(32, len(body["session_id"]))
        self.assertEqual(body["request_id"], response.headers["X-Request-ID"])

    def test_requires_token_and_uses_token_identity(self):
        runtime = FakeRuntime()
        app = create_test_app(runtime)

        with TestClient(app) as client:
            unauthorized = client.get(
                "/v1/me",
                headers={"X-Request-ID": "auth-001"},
            )
            identity = client.get("/v1/me", headers=auth_headers(user_id=11))
            chat = client.post(
                "/v1/chat",
                headers=auth_headers(user_id=11),
                json={"message": "查询积分"},
            )

        self.assertEqual(401, unauthorized.status_code)
        self.assertEqual("AUTH_REQUIRED", unauthorized.json()["code"])
        self.assertEqual("auth-001", unauthorized.headers["X-Request-ID"])
        self.assertEqual({"user_id": 11}, identity.json())
        self.assertEqual(11, chat.json()["user_id"])
        self.assertEqual(11, runtime.calls[0][0])


if __name__ == "__main__":
    unittest.main()
