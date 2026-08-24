from __future__ import annotations

import unittest

from langchain.agents.middleware import ModelRequest, ModelResponse
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from app.exchange.confirmation_store import ConfirmationStore
from app.context_window import (
    ContextWindowPolicy,
    apply_context_window,
    build_context_window_middleware,
)
from app.execution_context import bind_execution_context


class ContextWindowTest(unittest.TestCase):
    def test_keeps_recent_complete_turns_and_drops_oldest_turns(self):
        messages = []
        for index in range(40):
            messages.extend(
                [
                    HumanMessage(content=f"用户问题 {index} " + "x" * 80),
                    AIMessage(content=f"回答 {index} " + "y" * 80),
                ]
            )

        result = apply_context_window(
            messages=messages,
            system_message=SystemMessage(content="系统提示"),
            tools=[],
            policy=ContextWindowPolicy(max_tokens=256, max_turns=5),
        )

        self.assertLess(result.messages_after, result.messages_before)
        self.assertLessEqual(result.turns_after, 5)
        self.assertEqual("用户问题 39", result.messages[-2].content[:7])
        self.assertEqual("回答 39", result.messages[-1].content[:5])

    def test_does_not_split_tool_call_sequence_inside_current_turn(self):
        tool_call = {
            "name": "get_user_points",
            "args": {},
            "id": "call-current",
            "type": "tool_call",
        }
        messages = [
            HumanMessage(content="很久以前的问题 " + "x" * 1200),
            AIMessage(content="很久以前的回答"),
            HumanMessage(content="我现在有多少积分"),
            AIMessage(content="", tool_calls=[tool_call]),
            ToolMessage(
                content='{"data":{"points":900}}',
                tool_call_id="call-current",
                name="get_user_points",
            ),
            AIMessage(content="你当前有 900 积分"),
        ]

        result = apply_context_window(
            messages=messages,
            system_message=SystemMessage(content="系统提示"),
            tools=[],
            policy=ContextWindowPolicy(max_tokens=256, max_turns=6),
        )

        self.assertEqual(4, result.messages_after)
        self.assertIsInstance(result.messages[0], HumanMessage)
        self.assertEqual("call-current", result.messages[2].tool_call_id)
        self.assertEqual("你当前有 900 积分", result.messages[-1].content)

    def test_keeps_oversized_current_question(self):
        current = HumanMessage(content="z" * 4000)

        result = apply_context_window(
            messages=[current],
            system_message=SystemMessage(content="系统提示"),
            tools=[],
            policy=ContextWindowPolicy(max_tokens=256, max_turns=1),
        )

        self.assertEqual([current], result.messages)
        self.assertGreater(result.estimated_tokens_after, 256)

    def test_injects_pending_exchange_outside_trimmable_history(self):
        result = apply_context_window(
            messages=[HumanMessage(content="我再想想")],
            system_message=SystemMessage(content="原始系统提示"),
            tools=[],
            policy=ContextWindowPolicy(max_tokens=256, max_turns=1),
            pending_context="当前会话存在一笔等待确认的 6 号奖品兑换。",
        )

        self.assertTrue(result.pending_context_injected)
        self.assertIn("原始系统提示", result.system_message.content)
        self.assertIn("6 号奖品", result.system_message.content)

    def test_rejects_invalid_policy(self):
        with self.assertRaisesRegex(ValueError, "MAX_TOKENS"):
            ContextWindowPolicy(max_tokens=100)
        with self.assertRaisesRegex(ValueError, "MAX_TURNS"):
            ContextWindowPolicy(max_turns=0)

    def test_middleware_injects_pending_context_and_records_actual_usage(self):
        store = ConfirmationStore(token_factory=lambda: "pending-context-token")
        thread_id = "user:10:session:context-test"
        store.create(
            user_id=10,
            session_id=thread_id,
            award_id=6,
            award_name="智能手表",
            current_points=900,
            required_points=600,
            request_id="request-prepare",
        )
        middleware = build_context_window_middleware(
            policy=ContextWindowPolicy(max_tokens=512, max_turns=2),
            user_id=10,
            confirmation_store=store,
        )
        captured_requests = []

        def handler(request):
            captured_requests.append(request)
            return ModelResponse(
                result=[
                    AIMessage(
                        content="请明确确认或取消",
                        usage_metadata={
                            "input_tokens": 120,
                            "output_tokens": 8,
                            "total_tokens": 128,
                        },
                    )
                ]
            )

        request = ModelRequest(
            model=object(),
            messages=[HumanMessage(content="我再想想")],
            system_message=SystemMessage(content="系统提示"),
            tools=[],
        )
        with self.assertLogs("app.context_window", level="INFO") as logs:
            with bind_execution_context(thread_id):
                response = middleware.wrap_model_call(request, handler)

        self.assertEqual("请明确确认或取消", response.result[0].content)
        self.assertIn("智能手表", captured_requests[0].system_message.content)
        self.assertIn("pending_context=True", logs.output[0])
        self.assertIn("actual_input_tokens=120", logs.output[0])

if __name__ == "__main__":
    unittest.main()
