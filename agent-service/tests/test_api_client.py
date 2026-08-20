from __future__ import annotations

import unittest

import httpx

from app.api_client import BusinessApiClient
from app.trace import capture_tool_trace


class BusinessApiClientTest(unittest.TestCase):
    def test_retries_transient_get_and_preserves_envelope(self):
        calls = 0
        request_ids: list[str | None] = []

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            request_ids.append(request.headers.get("X-Request-ID"))
            if calls == 1:
                return httpx.Response(503)
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "code": "POINTS_FOUND",
                    "data": {"userId": 10, "points": 100},
                    "message": "查询成功",
                    "retryable": False,
                },
            )

        http_client = httpx.Client(
            base_url="http://test", transport=httpx.MockTransport(handler)
        )
        client = BusinessApiClient(
            "http://test", max_retries=1, client=http_client, sleep=lambda _: None
        )

        with capture_tool_trace("request-api-001"):
            result = client.get_user_points(10)

        self.assertEqual(2, calls)
        self.assertTrue(result.success)
        self.assertEqual("POINTS_FOUND", result.code)
        self.assertEqual(["request-api-001", "request-api-001"], request_ids)
        http_client.close()


if __name__ == "__main__":
    unittest.main()
