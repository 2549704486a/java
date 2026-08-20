from __future__ import annotations

import unittest

from app.confirmation_store import ConfirmationStore
from app.execution_context import bind_execution_context
from app.models import ToolEnvelope
from app.tools import build_tools
from app.trace import capture_tool_trace


class ToolClient:
    def __init__(self) -> None:
        self.submit_calls = 0

    def check_exchange_eligibility(self, user_id: int, award_id: int):
        return ToolEnvelope(
            success=True,
            code="ELIGIBILITY_CHECKED",
            data={
                "userId": user_id,
                "awardId": award_id,
                "eligible": True,
                "reasonCode": "ELIGIBLE",
                "reason": "满足兑换条件",
                "currentPoints": 300,
                "requiredPoints": 200,
                "pointsGap": 0,
            },
            message="查询成功",
        )

    def get_award_detail(self, award_id: int):
        return ToolEnvelope(
            success=True,
            code="AWARD_FOUND",
            data={
                "awardId": award_id,
                "name": "手表",
                "requiredPoints": 200,
                "inventory": 10,
            },
            message="查询成功",
        )

    def submit_exchange(self, **kwargs):
        self.submit_calls += 1
        return ToolEnvelope(
            success=True,
            code="EXCHANGE_PROCESSING",
            data=None,
            message="处理中",
        )


class ControlledExchangeToolsTest(unittest.TestCase):
    def test_tools_require_runtime_context_and_hide_token_from_trace(self):
        client = ToolClient()
        tools = build_tools(client, 10, confirmation_store=ConfirmationStore())
        prepare = next(tool for tool in tools if tool.name == "prepare_exchange")
        confirm = next(tool for tool in tools if tool.name == "confirm_exchange")

        without_context = prepare.invoke({"award_id": 6})
        self.assertEqual("EXECUTION_CONTEXT_UNAVAILABLE", without_context["code"])

        with bind_execution_context("user:10:session:a"), capture_tool_trace(
            "request-tool-001"
        ) as prepare_trace:
            prepared = prepare.invoke({"award_id": 6})
            confirmation_id = prepared["data"]["confirmationId"]
            same_turn = confirm.invoke({"confirmation_id": confirmation_id})

        with bind_execution_context("user:10:session:a"), capture_tool_trace(
            "request-tool-002"
        ) as confirm_trace:
            confirmed = confirm.invoke({"confirmation_id": confirmation_id})

        self.assertEqual("CONFIRMATION_REQUIRES_NEW_TURN", same_turn["code"])
        self.assertEqual("EXCHANGE_PROCESSING", confirmed["code"])
        self.assertEqual(1, client.submit_calls)
        confirm_event = confirm_trace.as_dicts()[0]
        self.assertEqual(
            {"confirmation_provided": True}, confirm_event["arguments"]
        )
        self.assertNotIn(confirmation_id, str(prepare_trace.as_dicts()))
        self.assertNotIn(confirmation_id, str(confirm_trace.as_dicts()))
