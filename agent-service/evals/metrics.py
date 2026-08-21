from __future__ import annotations

import math
import statistics
import threading
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler


@dataclass(frozen=True)
class TokenPricing:
    input_cost_per_million_usd: float
    output_cost_per_million_usd: float

    def __post_init__(self) -> None:
        if self.input_cost_per_million_usd < 0:
            raise ValueError("输入 Token 单价不能为负数")
        if self.output_cost_per_million_usd < 0:
            raise ValueError("输出 Token 单价不能为负数")


class ModelTimingHandler(BaseCallbackHandler):
    """Measure client-observed LLM call time without including Tool execution."""

    def __init__(self) -> None:
        self._started_at: dict[str, float] = {}
        self._events: list[dict[str, Any]] = []
        self._lock = threading.Lock()

    def on_chat_model_start(
        self,
        serialized: dict[str, Any],
        messages: list[list[Any]],
        *,
        run_id: Any,
        **kwargs: Any,
    ) -> None:
        self._start(run_id)

    def on_llm_start(
        self,
        serialized: dict[str, Any],
        prompts: list[str],
        *,
        run_id: Any,
        **kwargs: Any,
    ) -> None:
        self._start(run_id)

    def on_llm_end(
        self,
        response: Any,
        *,
        run_id: Any,
        **kwargs: Any,
    ) -> None:
        self._finish(run_id, completed=True)

    def on_llm_error(
        self,
        error: BaseException,
        *,
        run_id: Any,
        **kwargs: Any,
    ) -> None:
        self._finish(
            run_id,
            completed=False,
            error_type=error.__class__.__name__,
        )

    def _start(self, run_id: Any) -> None:
        key = str(run_id)
        with self._lock:
            # Some integrations may emit both generic and chat-model start events.
            self._started_at.setdefault(key, time.perf_counter())

    def _finish(
        self,
        run_id: Any,
        *,
        completed: bool,
        error_type: str | None = None,
    ) -> None:
        key = str(run_id)
        finished_at = time.perf_counter()
        with self._lock:
            started_at = self._started_at.pop(key, None)
            if started_at is None:
                return
            self._events.append(
                {
                    "elapsed_ms": round((finished_at - started_at) * 1000, 2),
                    "completed": completed,
                    "error_type": error_type,
                }
            )

    def summary(self) -> dict[str, Any]:
        with self._lock:
            events = list(self._events)
        elapsed_values = [float(event["elapsed_ms"]) for event in events]
        return {
            "calls": len(events),
            "failures": sum(not event["completed"] for event in events),
            "total_elapsed_ms": round(sum(elapsed_values), 2),
            "call_elapsed_ms": elapsed_values,
        }


def summarize_token_usage(
    results: list[dict[str, Any]],
    pricing: TokenPricing | None = None,
) -> dict[str, Any]:
    input_tokens = 0
    output_tokens = 0
    total_tokens = 0
    attempts_with_usage = 0
    for result in results:
        usage = result.get("usage", {})
        current_input = _token_value(usage.get("input_tokens"))
        current_output = _token_value(usage.get("output_tokens"))
        has_usage = any(
            isinstance(usage.get(key), int)
            for key in ("input_tokens", "output_tokens", "total_tokens")
        )
        if has_usage:
            attempts_with_usage += 1
        input_tokens += current_input
        output_tokens += current_output
        total_tokens += _token_value(
            usage.get("total_tokens"),
            default=current_input + current_output,
        )

    attempt_count = len(results)
    summary: dict[str, Any] = {
        "attempts_with_usage": attempts_with_usage,
        "usage_coverage_rate": round(attempts_with_usage / attempt_count, 4)
        if attempt_count
        else 0,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "average_tokens_per_attempt": round(total_tokens / attempt_count, 2)
        if attempt_count
        else 0,
    }
    summary["estimated_cost"] = estimate_token_cost(
        input_tokens,
        output_tokens,
        pricing,
    )
    return summary


def estimate_token_cost(
    input_tokens: int,
    output_tokens: int,
    pricing: TokenPricing | None,
) -> dict[str, Any]:
    if pricing is None:
        return {
            "available": False,
            "currency": "USD",
            "reason": "pricing_not_configured",
        }

    million = Decimal(1_000_000)
    input_cost = (
        Decimal(input_tokens)
        * Decimal(str(pricing.input_cost_per_million_usd))
        / million
    )
    output_cost = (
        Decimal(output_tokens)
        * Decimal(str(pricing.output_cost_per_million_usd))
        / million
    )
    return {
        "available": True,
        "currency": "USD",
        "input_cost_per_million_tokens": pricing.input_cost_per_million_usd,
        "output_cost_per_million_tokens": pricing.output_cost_per_million_usd,
        "input_cost": round(float(input_cost), 8),
        "output_cost": round(float(output_cost), 8),
        "total_cost": round(float(input_cost + output_cost), 8),
    }


def summarize_model_timing(results: list[dict[str, Any]]) -> dict[str, Any]:
    elapsed_values: list[float] = []
    failures = 0
    attempts_with_calls = 0
    for result in results:
        metrics = result.get("model_metrics", {})
        call_values = [
            float(value)
            for value in metrics.get("call_elapsed_ms", [])
            if isinstance(value, (int, float))
        ]
        if call_values:
            attempts_with_calls += 1
            elapsed_values.extend(call_values)
        failures += int(metrics.get("failures", 0))

    attempt_count = len(results)
    return {
        "calls": len(elapsed_values),
        "failures": failures,
        "attempts_with_calls": attempts_with_calls,
        "timing_coverage_rate": round(attempts_with_calls / attempt_count, 4)
        if attempt_count
        else 0,
        "total_elapsed_ms": round(sum(elapsed_values), 2),
        "average_call_elapsed_ms": round(statistics.mean(elapsed_values), 2)
        if elapsed_values
        else 0,
        "p95_call_elapsed_ms": round(_percentile(elapsed_values, 0.95), 2),
        "max_call_elapsed_ms": round(max(elapsed_values), 2)
        if elapsed_values
        else 0,
        "average_calls_per_attempt": round(len(elapsed_values) / attempt_count, 2)
        if attempt_count
        else 0,
    }


def _token_value(value: Any, default: int = 0) -> int:
    return value if isinstance(value, int) and value >= 0 else default


def _percentile(values: list[float], percentile_value: float) -> float:
    if not values:
        return 0
    ordered = sorted(values)
    rank = max(1, math.ceil(percentile_value * len(ordered)))
    return ordered[rank - 1]
