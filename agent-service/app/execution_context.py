from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar


_CURRENT_THREAD_ID: ContextVar[str | None] = ContextVar(
    "current_agent_thread_id",
    default=None,
)


@contextmanager
def bind_execution_context(thread_id: str | None) -> Iterator[None]:
    """把服务端生成的会话标识绑定到当前调用链，供高风险 Tool 校验。"""
    token = _CURRENT_THREAD_ID.set(thread_id)
    try:
        yield
    finally:
        _CURRENT_THREAD_ID.reset(token)


def current_thread_id() -> str | None:
    return _CURRENT_THREAD_ID.get()
