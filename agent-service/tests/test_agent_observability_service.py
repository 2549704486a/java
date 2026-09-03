from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from app.observability.models import (
    AgentRequestDetail,
    AgentRequestPage,
    AgentRequestRecord,
    AgentToolObservation,
)
from app.observability.service import AgentObservabilityService


class StubObservationStore:
    def __init__(self, requests=None, tools=None):
        self.requests = list(requests or [])
        self.tools = list(tools or [])

    def scan_requests(self, started_at, ended_at):
        return [
            item for item in self.requests if started_at <= item.started_at <= ended_at
        ]

    def scan_tools(self, request_ids):
        return [item for item in self.tools if item.request_id in request_ids]

    def list_requests(self, **kwargs):
        items = tuple(reversed(self.scan_requests(kwargs["started_at"], kwargs["ended_at"])))
        return AgentRequestPage(
            total=len(items),
            page=kwargs["page"],
            page_size=kwargs["page_size"],
            items=items,
        )

    def get_request(self, request_id):
        request = next(
            (item for item in self.requests if item.request_id == request_id), None
        )
        if request is None:
            return None
        tools = tuple(item for item in self.tools if item.request_id == request_id)
        return AgentRequestDetail(request=request, tool_calls=tools)


class AgentObservabilityServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 9, 3, 8, 0, tzinfo=timezone.utc)

    def request(
        self,
        index: int,
        *,
        agent_type: str = "USER",
        status: str = "COMPLETED",
        input_tokens: int | None = 10,
        output_tokens: int | None = 2,
    ) -> AgentRequestRecord:
        started_at = self.now - timedelta(hours=20 - index)
        return AgentRequestRecord(
            request_id=f"req-{index}",
            agent_type=agent_type,
            started_at=started_at,
            completed_at=started_at + timedelta(milliseconds=(index + 1) * 100),
            status=status,
            elapsed_ms=(index + 1) * 100,
            model_call_count=1,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            tool_call_count=0,
        )

    def test_empty_summary_preserves_unknown_ratios_and_latency(self):
        summary = AgentObservabilityService(StubObservationStore()).summarize(
            "24h", now=self.now
        )

        self.assertEqual(0, summary.requests.total)
        self.assertIsNone(summary.requests.completion.value)
        self.assertIsNone(summary.requests.latency.p95_ms)
        self.assertIsNone(summary.model_usage.input_tokens)
        self.assertEqual(24, len(summary.trend))

    def test_summary_uses_fixed_denominators_p95_and_token_coverage(self):
        requests = [self.request(index) for index in range(20)]
        requests[-1] = self.request(
            19,
            agent_type="OPERATOR",
            status="FAILED",
            input_tokens=None,
            output_tokens=None,
        )
        tools = [
            AgentToolObservation(
                request_id="req-0",
                sequence=1,
                tool_name="get_user_points",
                completed=True,
                business_success=True,
                elapsed_ms=10,
            ),
            AgentToolObservation(
                request_id="req-1",
                sequence=1,
                tool_name="get_user_points",
                completed=True,
                business_success=False,
                elapsed_ms=20,
            ),
            AgentToolObservation(
                request_id="req-2",
                sequence=1,
                tool_name="list_awards",
                completed=False,
                business_success=False,
                elapsed_ms=30,
            ),
        ]

        summary = AgentObservabilityService(
            StubObservationStore(requests, tools)
        ).summarize("24h", now=self.now)

        self.assertEqual((19, 20, 0.95), (
            summary.requests.completion.numerator,
            summary.requests.completion.denominator,
            summary.requests.completion.value,
        ))
        self.assertEqual(1050, summary.requests.latency.average_ms)
        self.assertEqual(1900, summary.requests.latency.p95_ms)
        self.assertEqual(19, summary.model_usage.covered_requests)
        self.assertEqual(190, summary.model_usage.input_tokens)
        self.assertEqual((2, 3), (
            summary.tools.execution_completion.numerator,
            summary.tools.execution_completion.denominator,
        ))
        self.assertEqual((1, 2, 0.5), (
            summary.tools.business_success.numerator,
            summary.tools.business_success.denominator,
            summary.tools.business_success.value,
        ))
        self.assertEqual(2, len(summary.tools_by_name))

    def test_list_validation_rejects_unbounded_page(self):
        service = AgentObservabilityService(StubObservationStore())

        with self.assertRaisesRegex(ValueError, "page_size"):
            service.list_requests(window="7d", page_size=101, now=self.now)


if __name__ == "__main__":
    unittest.main()
