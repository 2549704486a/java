from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

from app.web import create_app


class FakeRuntime:
    def __init__(self, should_fail: bool = False) -> None:
        self.should_fail = should_fail
        self.closed = False
        self.calls: list[tuple[int, str]] = []

    def health(self):
        return {
            "status": "UP",
            "model": "test-model",
            "cached_agents": 0,
            "agent_cache_size": 2,
            "skills": [],
        }

    def answer(self, user_id: int, message: str):
        self.calls.append((user_id, message))
        if self.should_fail:
            raise RuntimeError("不应返回给调用方的内部异常")
        return "测试回答", 12.345

    def close(self) -> None:
        self.closed = True


class AgentWebTest(unittest.TestCase):
    def test_health_and_chat_contract(self):
        runtime = FakeRuntime()
        app = create_app(lambda: runtime)

        with TestClient(app) as client:
            health = client.get("/health")
            response = client.post(
                "/v1/chat",
                headers={"X-Request-ID": "request-001"},
                json={"user_id": 10, "message": "  我有多少积分？  "},
            )

        self.assertEqual(200, health.status_code)
        self.assertEqual("UP", health.json()["status"])
        self.assertEqual(200, response.status_code)
        self.assertEqual("request-001", response.headers["X-Request-ID"])
        self.assertEqual(
            {
                "request_id": "request-001",
                "user_id": 10,
                "answer": "测试回答",
                "elapsed_ms": 12.35,
            },
            response.json(),
        )
        self.assertEqual([(10, "我有多少积分？")], runtime.calls)
        self.assertTrue(runtime.closed)

    def test_rejects_invalid_request_before_runtime_call(self):
        runtime = FakeRuntime()
        app = create_app(lambda: runtime)

        with TestClient(app) as client:
            invalid_user = client.post(
                "/v1/chat", json={"user_id": 0, "message": "查询积分"}
            )
            blank_message = client.post(
                "/v1/chat", json={"user_id": 10, "message": "   "}
            )

        self.assertEqual(422, invalid_user.status_code)
        self.assertEqual(422, blank_message.status_code)
        self.assertEqual([], runtime.calls)

    def test_returns_sanitized_error_and_generated_request_id(self):
        runtime = FakeRuntime(should_fail=True)
        app = create_app(lambda: runtime)

        with TestClient(app) as client:
            with self.assertLogs("app.web", level="ERROR"):
                response = client.post(
                    "/v1/chat",
                    headers={"X-Request-ID": "invalid request id"},
                    json={"user_id": 10, "message": "查询积分"},
                )

        body = response.json()
        self.assertEqual(503, response.status_code)
        self.assertEqual("AGENT_SERVICE_UNAVAILABLE", body["code"])
        self.assertNotIn("内部异常", body["message"])
        self.assertEqual(32, len(body["request_id"]))
        self.assertEqual(body["request_id"], response.headers["X-Request-ID"])


if __name__ == "__main__":
    unittest.main()
