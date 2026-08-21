from __future__ import annotations

import unittest
from unittest.mock import patch

from evals.metrics import (
    ModelTimingHandler,
    TokenPricing,
    summarize_model_timing,
    summarize_token_usage,
)


class EvalMetricsTest(unittest.TestCase):
    def test_model_timing_handler_records_success_and_failure(self):
        handler = ModelTimingHandler()

        with patch(
            "evals.metrics.time.perf_counter",
            side_effect=[1.0, 1.05, 2.0, 2.1],
        ):
            handler.on_chat_model_start({}, [], run_id="run-1")
            handler.on_llm_end(None, run_id="run-1")
            handler.on_llm_start({}, [], run_id="run-2")
            handler.on_llm_error(RuntimeError("boom"), run_id="run-2")

        summary = handler.summary()

        self.assertEqual(2, summary["calls"])
        self.assertEqual(1, summary["failures"])
        self.assertEqual([50.0, 100.0], summary["call_elapsed_ms"])
        self.assertEqual(150.0, summary["total_elapsed_ms"])

    def test_token_summary_estimates_cost_only_with_explicit_pricing(self):
        results = [
            {
                "usage": {
                    "input_tokens": 600_000,
                    "output_tokens": 1_000_000,
                    "total_tokens": 1_600_000,
                }
            },
            {
                "usage": {
                    "input_tokens": 400_000,
                    "output_tokens": 1_000_000,
                }
            },
        ]

        without_pricing = summarize_token_usage(results)
        with_pricing = summarize_token_usage(
            results,
            TokenPricing(
                input_cost_per_million_usd=0.5,
                output_cost_per_million_usd=1.5,
            ),
        )

        self.assertEqual(1_000_000, with_pricing["input_tokens"])
        self.assertEqual(2_000_000, with_pricing["output_tokens"])
        self.assertEqual(3_000_000, with_pricing["total_tokens"])
        self.assertFalse(without_pricing["estimated_cost"]["available"])
        self.assertEqual(3.5, with_pricing["estimated_cost"]["total_cost"])

    def test_model_timing_summary_aggregates_calls_across_attempts(self):
        results = [
            {
                "model_metrics": {
                    "call_elapsed_ms": [50, 70],
                    "failures": 0,
                }
            },
            {
                "model_metrics": {
                    "call_elapsed_ms": [100],
                    "failures": 1,
                }
            },
        ]

        summary = summarize_model_timing(results)

        self.assertEqual(3, summary["calls"])
        self.assertEqual(1, summary["failures"])
        self.assertEqual(73.33, summary["average_call_elapsed_ms"])
        self.assertEqual(100, summary["p95_call_elapsed_ms"])
        self.assertEqual(1.5, summary["average_calls_per_attempt"])


if __name__ == "__main__":
    unittest.main()
