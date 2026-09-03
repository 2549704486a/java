from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler

from app.observability.models import (
    AgentRequestObservation,
    AgentRunStatus,
    AgentToolObservation,
    AgentType,
)
from app.trace import ToolExecutionTrace


@dataclass(frozen=True)
class ModelUsageSnapshot:
    call_count: int
    input_tokens: int | None
    output_tokens: int | None


class ModelUsageHandler(BaseCallbackHandler):
    """只累计当前 invoke 的模型调用，缺少任一次用量时保持未知。"""

    def __init__(self) -> None:
        self._runs: set[str] = set()
        self._usage_by_run: dict[str, tuple[int, int] | None] = {}
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
        key = str(run_id)
        usage = _extract_usage(response)
        with self._lock:
            self._runs.add(key)
            self._usage_by_run[key] = usage

    def on_llm_error(
        self,
        error: BaseException,
        *,
        run_id: Any,
        **kwargs: Any,
    ) -> None:
        key = str(run_id)
        with self._lock:
            self._runs.add(key)
            self._usage_by_run[key] = None

    def snapshot(self) -> ModelUsageSnapshot:
        with self._lock:
            runs = set(self._runs)
            usage_by_run = dict(self._usage_by_run)
        if not runs:
            return ModelUsageSnapshot(0, 0, 0)
        if any(usage_by_run.get(run_id) is None for run_id in runs):
            return ModelUsageSnapshot(len(runs), None, None)
        return ModelUsageSnapshot(
            call_count=len(runs),
            input_tokens=sum(usage_by_run[run_id][0] for run_id in runs),
            output_tokens=sum(usage_by_run[run_id][1] for run_id in runs),
        )

    def _start(self, run_id: Any) -> None:
        with self._lock:
            self._runs.add(str(run_id))


class AgentObservationContext:
    """汇总单次 Agent 请求的模型与 Tool 摘要。"""

    def __init__(
        self,
        request_id: str,
        agent_type: AgentType,
        *,
        wall_clock: Callable[[], datetime] | None = None,
        monotonic_clock: Callable[[], float] | None = None,
    ) -> None:
        self.request_id = request_id
        self.agent_type = agent_type
        self._wall_clock = wall_clock or (lambda: datetime.now(timezone.utc))
        self._monotonic_clock = monotonic_clock or time.perf_counter
        self.started_at = _aware_utc(self._wall_clock())
        self._started_monotonic = self._monotonic_clock()
        self._tool_calls: tuple[AgentToolObservation, ...] = ()
        self.model_usage_handler = ModelUsageHandler()

    def record_tool_traces(self, traces: Sequence[ToolExecutionTrace]) -> None:
        self._tool_calls = tuple(
            AgentToolObservation(
                request_id=self.request_id,
                sequence=item.sequence,
                tool_name=item.tool_name,
                transport=item.transport,
                completed=item.completed,
                business_success=item.business_success,
                result_code=item.result_code,
                elapsed_ms=max(0, round(item.elapsed_ms)),
                error_type=item.error_type,
            )
            for item in traces
        )

    def finish(
        self,
        status: AgentRunStatus,
        *,
        error: BaseException | None = None,
    ) -> AgentRequestObservation:
        completed_at = _aware_utc(self._wall_clock())
        if completed_at < self.started_at:
            completed_at = self.started_at
        usage = self.model_usage_handler.snapshot()
        return AgentRequestObservation(
            request_id=self.request_id,
            agent_type=self.agent_type,
            started_at=self.started_at,
            completed_at=completed_at,
            status=status,
            elapsed_ms=max(
                0,
                round((self._monotonic_clock() - self._started_monotonic) * 1000),
            ),
            model_call_count=usage.call_count,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            error_type=error.__class__.__name__[:128] if error is not None else None,
            tool_calls=self._tool_calls,
        )


_ACTIVE_OBSERVATION: ContextVar[AgentObservationContext | None] = ContextVar(
    "active_agent_observation",
    default=None,
)


@contextmanager
def capture_agent_observation(
    request_id: str,
    agent_type: AgentType,
    *,
    wall_clock: Callable[[], datetime] | None = None,
    monotonic_clock: Callable[[], float] | None = None,
) -> Iterator[AgentObservationContext]:
    context = AgentObservationContext(
        request_id,
        agent_type,
        wall_clock=wall_clock,
        monotonic_clock=monotonic_clock,
    )
    token = _ACTIVE_OBSERVATION.set(context)
    try:
        yield context
    finally:
        _ACTIVE_OBSERVATION.reset(token)


def current_agent_observation() -> AgentObservationContext | None:
    return _ACTIVE_OBSERVATION.get()


def record_current_tool_traces(traces: Sequence[ToolExecutionTrace]) -> None:
    context = current_agent_observation()
    if context is not None:
        context.record_tool_traces(traces)


def current_model_usage_handler() -> ModelUsageHandler | None:
    context = current_agent_observation()
    return context.model_usage_handler if context is not None else None


def _extract_usage(response: Any) -> tuple[int, int] | None:
    values: list[tuple[int, int]] = []
    for group in getattr(response, "generations", None) or []:
        for generation in group:
            message = getattr(generation, "message", None)
            usage = getattr(message, "usage_metadata", None)
            parsed = _usage_values(usage)
            if parsed is not None:
                values.append(parsed)
    if values:
        return (
            sum(item[0] for item in values),
            sum(item[1] for item in values),
        )

    llm_output = getattr(response, "llm_output", None)
    if isinstance(llm_output, dict):
        usage = llm_output.get("token_usage") or llm_output.get("usage")
        return _usage_values(usage)
    return None


def _usage_values(usage: Any) -> tuple[int, int] | None:
    if not isinstance(usage, dict):
        return None
    input_value = usage.get("input_tokens", usage.get("prompt_tokens"))
    output_value = usage.get("output_tokens", usage.get("completion_tokens"))
    if not isinstance(input_value, int) or not isinstance(output_value, int):
        return None
    if input_value < 0 or output_value < 0:
        return None
    return input_value, output_value


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("观测时间必须包含时区")
    return value.astimezone(timezone.utc)
