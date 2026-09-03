from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from pydantic import ValidationError

from app.observability.models import AgentRequestObservation, AgentToolObservation


class AgentObservationModelsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.started_at = datetime(2026, 9, 3, 8, 0, tzinfo=timezone.utc)

    def tool(self, *, request_id: str = "req-1", sequence: int = 1):
        return AgentToolObservation(
            request_id=request_id,
            sequence=sequence,
            tool_name="get_campaign_funnel",
            transport="REST",
            completed=True,
            business_success=True,
            result_code="CAMPAIGN_FUNNEL_READY",
            elapsed_ms=42,
        )

    def request(self, **overrides):
        values = {
            "request_id": "req-1",
            "agent_type": "OPERATOR",
            "started_at": self.started_at,
            "completed_at": self.started_at + timedelta(milliseconds=120),
            "status": "COMPLETED",
            "elapsed_ms": 120,
            "model_call_count": 1,
            "input_tokens": 80,
            "output_tokens": 20,
            "tool_calls": (self.tool(),),
        }
        values.update(overrides)
        return AgentRequestObservation(**values)

    def test_accepts_minimal_observation_without_identity_or_content(self):
        observation = self.request()

        self.assertEqual(1, observation.tool_call_count)
        fields = AgentRequestObservation.model_fields
        self.assertNotIn("user_id", fields)
        self.assertNotIn("session_id", fields)
        self.assertNotIn("message", fields)
        self.assertNotIn("answer", fields)

    def test_tokens_are_both_known_or_both_unknown(self):
        with self.assertRaisesRegex(ValidationError, "必须同时已知或同时未知"):
            self.request(output_tokens=None)

        observation = self.request(input_tokens=None, output_tokens=None)
        self.assertIsNone(observation.input_tokens)

    def test_request_without_model_call_has_zero_tokens(self):
        observation = self.request(
            model_call_count=0,
            input_tokens=0,
            output_tokens=0,
        )
        self.assertEqual(0, observation.input_tokens)

        with self.assertRaisesRegex(ValidationError, "Token 必须为 0"):
            self.request(
                model_call_count=0,
                input_tokens=None,
                output_tokens=None,
            )

    def test_rejects_tool_from_another_request_or_non_contiguous_sequence(self):
        with self.assertRaisesRegex(ValidationError, "request_id 必须与请求一致"):
            self.request(tool_calls=(self.tool(request_id="req-2"),))
        with self.assertRaisesRegex(ValidationError, "从 1 开始并连续递增"):
            self.request(tool_calls=(self.tool(sequence=2),))

    def test_rejects_end_before_start(self):
        with self.assertRaisesRegex(ValidationError, "不能早于"):
            self.request(completed_at=self.started_at - timedelta(milliseconds=1))


if __name__ == "__main__":
    unittest.main()
