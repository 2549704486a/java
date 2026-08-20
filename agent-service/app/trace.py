from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, dataclass
from typing import Any, TypeVar


T = TypeVar("T")


@dataclass(frozen=True)
class ToolExecutionTrace:
    sequence: int
    tool_name: str
    arguments: dict[str, Any]
    completed: bool
    business_success: bool | None
    result_code: str | None
    elapsed_ms: float
    error_type: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class ToolTraceSession:
    """保存一次 Agent 请求中的 Tool 执行摘要。"""

    def __init__(self, correlation_id: str) -> None:
        self.correlation_id = correlation_id
        self._events: list[ToolExecutionTrace] = []
        self._lock = threading.Lock()

    def record(
        self,
        *,
        tool_name: str,
        arguments: dict[str, Any],
        completed: bool,
        business_success: bool | None,
        result_code: str | None,
        elapsed_ms: float,
        error_type: str | None = None,
    ) -> None:
        with self._lock:
            self._events.append(
                ToolExecutionTrace(
                    sequence=len(self._events) + 1,
                    tool_name=tool_name,
                    arguments=dict(arguments),
                    completed=completed,
                    business_success=business_success,
                    result_code=result_code,
                    elapsed_ms=round(elapsed_ms, 2),
                    error_type=error_type,
                )
            )

    def snapshot(self) -> list[ToolExecutionTrace]:
        with self._lock:
            return list(self._events)

    def as_dicts(self) -> list[dict[str, Any]]:
        return [event.as_dict() for event in self.snapshot()]


_ACTIVE_TRACE: ContextVar[ToolTraceSession | None] = ContextVar(
    "active_tool_trace",
    default=None,
)


@contextmanager
def capture_tool_trace(correlation_id: str) -> Iterator[ToolTraceSession]:
    # 将轨迹会话绑定到当前请求上下文，后续 Tool 无需逐层传递 session 参数。
    session = ToolTraceSession(correlation_id)
    token = _ACTIVE_TRACE.set(session)
    try:
        yield session
    finally:
        # 请求结束后恢复原上下文，避免线程复用时把轨迹串到下一次请求。
        _ACTIVE_TRACE.reset(token)


def current_correlation_id() -> str | None:
    session = _ACTIVE_TRACE.get()
    return session.correlation_id if session is not None else None


def execute_traced(
    tool_name: str,
    arguments: dict[str, Any],
    operation: Callable[[], T],
) -> T:
    # 所有 Tool/Skill 都从这个统一入口执行，保证耗时和结果字段口径一致。
    started = time.perf_counter()
    session = _ACTIVE_TRACE.get()
    try:
        result = operation()
    except Exception as exc:
        if session is not None:
            session.record(
                tool_name=tool_name,
                arguments=arguments,
                completed=False,
                business_success=None,
                result_code=None,
                elapsed_ms=(time.perf_counter() - started) * 1000,
                error_type=exc.__class__.__name__,
            )
        # 轨迹只负责观察，不改变原有异常处理语义。
        raise

    if session is not None:
        business_success, result_code = _summarize_result(result)
        session.record(
            tool_name=tool_name,
            arguments=arguments,
            completed=True,
            business_success=business_success,
            result_code=result_code,
            elapsed_ms=(time.perf_counter() - started) * 1000,
        )
    return result


def _summarize_result(result: Any) -> tuple[bool | None, str | None]:
    # 轨迹只保留可统计摘要，不复制完整业务数据，避免日志过大或泄露敏感字段。
    payload = result
    model_dump = getattr(result, "model_dump", None)
    if callable(model_dump):
        payload = model_dump(mode="json")
    if not isinstance(payload, dict):
        return None, None

    success = payload.get("success")
    business_success = success if isinstance(success, bool) else None
    result_code = payload.get("code") or payload.get("status") or payload.get(
        "reason_code"
    )
    return business_success, str(result_code) if result_code is not None else None
