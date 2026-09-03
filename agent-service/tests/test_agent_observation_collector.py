from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.observability.collector import (
    ModelUsageHandler,
    capture_agent_observation,
    current_agent_observation,
)
from app.trace import ToolExecutionTrace


def llm_response(input_tokens: int | None, output_tokens: int | None):
    usage = (
        {"input_tokens": input_tokens, "output_tokens": output_tokens}
        if input_tokens is not None and output_tokens is not None
        else None
    )
    message = SimpleNamespace(usage_metadata=usage)
    generation = SimpleNamespace(message=message)
    return SimpleNamespace(generations=[[generation]], llm_output=None)


class ModelUsageHandlerTest(unittest.TestCase):
    def test_counts_each_run_once_and_sums_complete_usage(self):
        handler = ModelUsageHandler()
        handler.on_chat_model_start({}, [], run_id="run-1")
        handler.on_llm_start({}, [], run_id="run-1")
        handler.on_llm_end(llm_response(10, 2), run_id="run-1")
        handler.on_chat_model_start({}, [], run_id="run-2")
        handler.on_llm_end(llm_response(20, 3), run_id="run-2")

        snapshot = handler.snapshot()

        self.assertEqual(2, snapshot.call_count)
        self.assertEqual(30, snapshot.input_tokens)
        self.assertEqual(5, snapshot.output_tokens)

    def test_any_missing_usage_makes_request_usage_unknown(self):
        handler = ModelUsageHandler()
        handler.on_chat_model_start({}, [], run_id="run-1")
        handler.on_llm_end(llm_response(10, 2), run_id="run-1")
        handler.on_chat_model_start({}, [], run_id="run-2")
        handler.on_llm_end(llm_response(None, None), run_id="run-2")

        snapshot = handler.snapshot()

        self.assertEqual(2, snapshot.call_count)
        self.assertIsNone(snapshot.input_tokens)
        self.assertIsNone(snapshot.output_tokens)

    def test_no_model_call_has_known_zero_usage(self):
        snapshot = ModelUsageHandler().snapshot()

        self.assertEqual((0, 0, 0), (
            snapshot.call_count,
            snapshot.input_tokens,
            snapshot.output_tokens,
        ))


class AgentObservationContextTest(unittest.TestCase):
    def test_builds_sanitized_snapshot_and_preserves_unknown_business_result(self):
        started_at = datetime(2026, 9, 3, 8, 0, tzinfo=timezone.utc)
        wall_times = iter([started_at, started_at + timedelta(milliseconds=200)])
        monotonic_times = iter([10.0, 10.2])

        with capture_agent_observation(
            "request-1",
            "USER",
            wall_clock=lambda: next(wall_times),
            monotonic_clock=lambda: next(monotonic_times),
        ) as context:
            self.assertIs(context, current_agent_observation())
            context.record_tool_traces(
                [
                    ToolExecutionTrace(
                        sequence=1,
                        tool_name="load_skill",
                        arguments={"query": "sensitive content"},
                        completed=True,
                        business_success=None,
                        result_code=None,
                        elapsed_ms=12.4,
                    )
                ]
            )
            observation = context.finish("COMPLETED")

        self.assertIsNone(current_agent_observation())
        self.assertEqual(200, observation.elapsed_ms)
        self.assertEqual(0, observation.model_call_count)
        self.assertIsNone(observation.tool_calls[0].business_success)
        self.assertNotIn(
            "arguments",
            observation.tool_calls[0].model_dump(),
        )

    def test_failed_snapshot_only_keeps_error_type(self):
        started_at = datetime(2026, 9, 3, 8, 0, tzinfo=timezone.utc)
        wall_times = iter([started_at, started_at])
        monotonic_times = iter([1.0, 1.0])

        with capture_agent_observation(
            "request-2",
            "OPERATOR",
            wall_clock=lambda: next(wall_times),
            monotonic_clock=lambda: next(monotonic_times),
        ) as context:
            observation = context.finish(
                "FAILED",
                error=RuntimeError("secret database details"),
            )

        self.assertEqual("RuntimeError", observation.error_type)
        self.assertNotIn("secret database details", observation.model_dump_json())


if __name__ == "__main__":
    unittest.main()
