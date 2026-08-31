from __future__ import annotations

import json
import os
import unittest
from urllib.parse import urlsplit, urlunsplit

from langchain.agents import create_agent
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from app.api_client import BusinessApiClient
from app.config import Settings
from app.mcp_award_tool import discover_award_detail_mcp_tool
from app.trace import capture_tool_trace


RUN_MCP_INTEGRATION = os.getenv("RUN_MCP_INTEGRATION", "false").lower() == "true"


class GroundedToolCallingFakeModel(FakeMessagesListChatModel):
    award_id: int

    def bind_tools(self, tools, *, tool_choice=None, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        tool_messages = [
            message for message in messages if isinstance(message, ToolMessage)
        ]
        if not tool_messages:
            response = AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "get_award_detail",
                        "args": {"award_id": self.award_id},
                        "id": "mcp-award-call-1",
                        "type": "tool_call",
                    }
                ],
            )
        else:
            envelope = tool_messages[-1].artifact["structured_content"]
            award = envelope["data"]
            response = AIMessage(
                content=(
                    f"{award['name']}需要 {award['requiredPoints']} 积分。"
                )
            )
        return ChatResult(generations=[ChatGeneration(message=response)])


@unittest.skipUnless(
    RUN_MCP_INTEGRATION,
    "set RUN_MCP_INTEGRATION=true and start the Java MCP endpoint",
)
class McpAwardIntegrationTest(unittest.IsolatedAsyncioTestCase):
    def settings(self) -> Settings:
        return Settings(
            award_detail_transport="mcp",
            award_detail_mcp_url=os.getenv(
                "MCP_INTEGRATION_URL",
                "http://127.0.0.1:18088/mcp",
            ),
            award_detail_mcp_initialization_timeout_seconds=10,
            award_detail_mcp_call_timeout_seconds=10,
        )

    async def test_mcp_envelopes_match_rest_for_found_and_missing_awards(self):
        settings = self.settings()
        binding = await discover_award_detail_mcp_tool(settings)
        with BusinessApiClient(
            self._rest_base_url(settings.award_detail_mcp_url),
            max_retries=0,
        ) as rest:
            for award_id in (self._existing_award_id(), 99_999_999):
                with self.subTest(award_id=award_id):
                    with capture_tool_trace(f"mcp-integration-{award_id}") as traces:
                        mcp_result = await binding.tool.ainvoke(
                            {"award_id": award_id}
                        )
                    rest_result = rest.get_award_detail(award_id).model_dump(
                        mode="json",
                        by_alias=True,
                    )

                    self.assertEqual(rest_result, self._mcp_envelope(mcp_result))
                    event = traces.as_dicts()[0]
                    self.assertEqual("mcp", event["transport"])
                    self.assertEqual(rest_result["code"], event["result_code"])

    async def test_agent_receives_one_real_mcp_tool_result(self):
        award_id = self._existing_award_id()
        binding = await discover_award_detail_mcp_tool(self.settings())
        model = GroundedToolCallingFakeModel(
            responses=[],
            award_id=award_id,
        )
        agent = create_agent(
            model=model,
            tools=[binding.tool],
            system_prompt="必须根据 Tool 返回的结构化结果回答。",
        )

        with capture_tool_trace("real-agent-mcp") as traces:
            result = await agent.ainvoke(
                {
                    "messages": [
                        HumanMessage(content=f"查询 {award_id} 号奖品")
                    ]
                }
            )

        tool_messages = [
            message
            for message in result["messages"]
            if isinstance(message, ToolMessage)
        ]
        self.assertEqual(1, len(tool_messages))
        self.assertEqual("get_award_detail", tool_messages[0].name)
        envelope = tool_messages[0].artifact["structured_content"]
        self.assertEqual("AWARD_FOUND", envelope["code"])
        self.assertEqual(award_id, envelope["data"]["awardId"])
        final_answer = result["messages"][-1].content
        self.assertIn(envelope["data"]["name"], final_answer)
        self.assertIn(str(envelope["data"]["requiredPoints"]), final_answer)
        self.assertEqual(
            ["get_award_detail"],
            [event["tool_name"] for event in traces.as_dicts()],
        )
        self.assertEqual("mcp", traces.as_dicts()[0]["transport"])

    @staticmethod
    def _existing_award_id() -> int:
        return int(os.getenv("MCP_INTEGRATION_AWARD_ID", "6"))

    @staticmethod
    def _rest_base_url(mcp_url: str) -> str:
        parsed = urlsplit(mcp_url)
        return urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))

    @staticmethod
    def _mcp_envelope(result) -> dict:
        for block in result:
            if isinstance(block, dict) and block.get("type") == "text":
                return json.loads(block["text"])
        raise AssertionError("MCP result does not contain a JSON text block")


if __name__ == "__main__":
    unittest.main()
