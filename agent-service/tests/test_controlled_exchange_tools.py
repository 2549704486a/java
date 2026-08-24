from __future__ import annotations

import unittest

from app.exchange.confirmation_store import ConfirmationStore
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
    def test_prepare_requires_context_and_hides_token_from_model_and_trace(self):
        client = ToolClient()
        tools = build_tools(client, 10, confirmation_store=ConfirmationStore())
        prepare = next(tool for tool in tools if tool.name == "prepare_exchange")
        self.assertNotIn("confirm_exchange", {tool.name for tool in tools})

        without_context = prepare.invoke({"award_id": 6})
        self.assertEqual("EXECUTION_CONTEXT_UNAVAILABLE", without_context["code"])

        with bind_execution_context("user:10:session:a"), capture_tool_trace(
            "request-tool-001"
        ) as prepare_trace:
            prepared = prepare.invoke({"award_id": 6})

        self.assertEqual("EXCHANGE_CONFIRMATION_REQUIRED", prepared["code"])
        self.assertNotIn("confirmationId", prepared["data"])
        self.assertEqual(0, client.submit_calls)
        self.assertNotIn("confirmationId", str(prepare_trace.as_dicts()))
        self.assertNotIn("token_urlsafe", str(prepare_trace.as_dicts()))
