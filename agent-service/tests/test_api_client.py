from __future__ import annotations

import unittest

import httpx

from app.api_client import BusinessApiClient, BusinessApiError
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

    def test_post_exchange_is_sent_once_with_bound_headers(self):
        calls = 0
        observed_headers: dict[str, str] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            observed_headers["request_id"] = request.headers["X-Request-ID"]
            observed_headers["idempotency_key"] = request.headers["Idempotency-Key"]
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "code": "EXCHANGE_PROCESSING",
                    "data": None,
                    "message": "处理中",
                    "retryable": False,
                },
            )

        http_client = httpx.Client(
            base_url="http://test", transport=httpx.MockTransport(handler)
        )
        client = BusinessApiClient("http://test", max_retries=5, client=http_client)

        result = client.submit_exchange(
            user_id=10,
            award_id=6,
            request_id="request-write-001",
            idempotency_key="confirmation-write-001",
        )

        self.assertEqual("EXCHANGE_PROCESSING", result.code)
        self.assertEqual(1, calls)
        self.assertEqual("request-write-001", observed_headers["request_id"])
        self.assertEqual(
            "confirmation-write-001", observed_headers["idempotency_key"]
        )
        http_client.close()

    def test_post_exchange_never_retries_unknown_server_error(self):
        calls = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return httpx.Response(503)

        http_client = httpx.Client(
            base_url="http://test", transport=httpx.MockTransport(handler)
        )
        client = BusinessApiClient("http://test", max_retries=5, client=http_client)

        with self.assertRaisesRegex(BusinessApiError, "无法判断") as raised:
            client.submit_exchange(
                user_id=10,
                award_id=6,
                request_id="request-write-002",
                idempotency_key="confirmation-write-002",
            )

        self.assertEqual("SUBMISSION_UNKNOWN", raised.exception.code)
        self.assertFalse(raised.exception.retryable)
        self.assertEqual(1, calls)
        http_client.close()


if __name__ == "__main__":
    unittest.main()
