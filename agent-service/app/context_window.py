from __future__ import annotations

import logging
from collections.abc import Awaitable
from dataclasses import dataclass
from typing import Any, Callable, Sequence

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langchain_core.messages.utils import count_tokens_approximately

from app.exchange.confirmation_store import ConfirmationStoreBackend
from app.execution_context import current_thread_id


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ContextWindowPolicy:
    """限制单次模型可见上下文，不修改 checkpointer 中的完整会话状态。"""

    max_tokens: int = 6000
    max_turns: int = 12

    def __post_init__(self) -> None:
        if self.max_tokens < 256:
            raise ValueError("AGENT_CONTEXT_MAX_TOKENS 不能小于 256")
        if self.max_turns < 1:
            raise ValueError("AGENT_CONTEXT_MAX_TURNS 不能小于 1")


@dataclass(frozen=True)
class ContextWindowResult:
    messages: list[BaseMessage]
    system_message: SystemMessage | None
    estimated_tokens_before: int
    estimated_tokens_after: int
    messages_before: int
    messages_after: int
    turns_before: int
    turns_after: int
    pending_context_injected: bool

    @property
    def trimmed_messages(self) -> int:
        return self.messages_before - self.messages_after


def _conversation_turns(messages: Sequence[BaseMessage]) -> list[list[BaseMessage]]:
    """按 HumanMessage 划分完整轮次，ToolMessage 会留在触发它的同一轮。"""
    turns: list[list[BaseMessage]] = []
    for message in messages:
        if isinstance(message, HumanMessage) or not turns:
            turns.append([message])
        else:
            turns[-1].append(message)
    return turns


def _with_pending_context(
    system_message: SystemMessage | None,
    pending_context: str | None,
) -> tuple[SystemMessage | None, bool]:
    if not pending_context:
        return system_message, False
    original = system_message.text if system_message is not None else ""
    content = f"{original.rstrip()}\n\n{pending_context}".strip()
    return SystemMessage(content=content), True


def _estimate_tokens(
    system_message: SystemMessage | None,
    messages: Sequence[BaseMessage],
    tools: Sequence[Any],
) -> int:
    all_messages = ([system_message] if system_message is not None else []) + list(
        messages
    )
    return count_tokens_approximately(all_messages, tools=list(tools))


def apply_context_window(
    *,
    messages: Sequence[BaseMessage],
    system_message: SystemMessage | None,
    tools: Sequence[Any],
    policy: ContextWindowPolicy,
    pending_context: str | None = None,
) -> ContextWindowResult:
    """优先保留当前轮和最近完整轮次，直到达到轮次或 token 预算。"""
    effective_system, pending_injected = _with_pending_context(
        system_message,
        pending_context,
    )
    turns = _conversation_turns(messages)
    candidate_turns = turns[-policy.max_turns :]
    selected_turns: list[list[BaseMessage]] = []

    # 当前轮即使自身超过预算也必须保留，否则模型看不到本次问题。
    for turn in reversed(candidate_turns):
        candidate = [turn, *selected_turns]
        candidate_messages = [message for item in candidate for message in item]
        estimated = _estimate_tokens(
            effective_system,
            candidate_messages,
            tools,
        )
        if selected_turns and estimated > policy.max_tokens:
            break
        selected_turns = candidate

    selected_messages = [
        message for turn in selected_turns for message in turn
    ]
    return ContextWindowResult(
        messages=selected_messages,
        system_message=effective_system,
        estimated_tokens_before=_estimate_tokens(
            effective_system,
            messages,
            tools,
        ),
        estimated_tokens_after=_estimate_tokens(
            effective_system,
            selected_messages,
            tools,
        ),
        messages_before=len(messages),
        messages_after=len(selected_messages),
        turns_before=len(turns),
        turns_after=len(selected_turns),
        pending_context_injected=pending_injected,
    )


def _pending_exchange_context(
    confirmation_store: ConfirmationStoreBackend | None,
    user_id: int,
) -> str | None:
    thread_id = current_thread_id()
    if confirmation_store is None or thread_id is None:
        return None
    pending = confirmation_store.pending_for(user_id=user_id, session_id=thread_id)
    if pending is None:
        return None
    return (
        "当前会话存在一笔等待用户确认的兑换："
        f"奖品 {pending.award_name}（ID={pending.award_id}），"
        f"需要 {pending.required_points} 积分。"
        "只有用户明确确认或取消时，才能进入对应的受控流程。"
    )


def _actual_usage(response: ModelResponse) -> tuple[int | None, int | None]:
    input_tokens = 0
    output_tokens = 0
    found = False
    for message in response.result:
        usage = getattr(message, "usage_metadata", None)
        if not isinstance(usage, dict):
            continue
        found = True
        input_tokens += int(usage.get("input_tokens") or 0)
        output_tokens += int(usage.get("output_tokens") or 0)
    if not found:
        return None, None
    return input_tokens, output_tokens


class ContextWindowMiddleware(AgentMiddleware):
    """同步与异步 Agent 共用同一套上下文裁剪规则。"""

    def __init__(
        self,
        *,
        policy: ContextWindowPolicy,
        user_id: int,
        confirmation_store: ConfirmationStoreBackend | None,
    ) -> None:
        self._policy = policy
        self._user_id = user_id
        self._confirmation_store = confirmation_store

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        result, next_request = self._prepare(request)
        response = handler(next_request)
        self._log(result, response)
        return response

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        result, next_request = self._prepare(request)
        response = await handler(next_request)
        self._log(result, response)
        return response

    def _prepare(
        self,
        request: ModelRequest,
    ) -> tuple[ContextWindowResult, ModelRequest]:
        pending_exchange = _pending_exchange_context(
            self._confirmation_store,
            self._user_id,
        )
        result = apply_context_window(
            messages=request.messages,
            system_message=request.system_message,
            tools=request.tools,
            policy=self._policy,
            pending_context=pending_exchange,
        )
        return result, request.override(
            messages=result.messages,
            system_message=result.system_message,
        )

    def _log(
        self,
        result: ContextWindowResult,
        response: ModelResponse,
    ) -> None:
        actual_input_tokens, actual_output_tokens = _actual_usage(response)
        logger.info(
            "agent_context_window thread_id=%s max_tokens=%s "
            "estimated_before=%s estimated_after=%s messages_before=%s "
            "messages_after=%s turns_before=%s turns_after=%s "
            "trimmed_messages=%s pending_context=%s actual_input_tokens=%s "
            "actual_output_tokens=%s",
            current_thread_id() or "-",
            self._policy.max_tokens,
            result.estimated_tokens_before,
            result.estimated_tokens_after,
            result.messages_before,
            result.messages_after,
            result.turns_before,
            result.turns_after,
            result.trimmed_messages,
            result.pending_context_injected,
            actual_input_tokens if actual_input_tokens is not None else "-",
            actual_output_tokens if actual_output_tokens is not None else "-",
        )


def build_context_window_middleware(
    *,
    policy: ContextWindowPolicy,
    user_id: int,
    confirmation_store: ConfirmationStoreBackend | None,
):
    """构建模型调用中间件；持久化历史不变，仅裁剪本次模型输入。"""
    return ContextWindowMiddleware(
        policy=policy,
        user_id=user_id,
        confirmation_store=confirmation_store,
    )
