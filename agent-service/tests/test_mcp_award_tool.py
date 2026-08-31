from __future__ import annotations

import asyncio
import unittest

from langchain_mcp_adapters.interceptors import MCPToolCallRequest
from mcp.types import CallToolResult

from app.config import Settings
from app.execution_context import bind_execution_context
from app.mcp_award_tool import (
    JAVA_LONG_MAX,
    McpAwardToolInitializationError,
    McpAwardTraceInterceptor,
    discover_award_detail_mcp_tool,
)
from app.tools import build_tools
from app.trace import capture_tool_trace
from evals.fixtures import FixtureBusinessApiClient


EXPECTED_SCHEMA = {
    "type": "object",
    "properties": {
        "award_id": {
            "type": "integer",
            "minimum": 1,
            "maximum": JAVA_LONG_MAX,
            "description": "奖品 ID",
        }
    },
    "required": ["award_id"],
    "additionalProperties": False,
}


class FakeTool:
    def __init__(self, name: str, schema: dict | None = None) -> None:
        self.name = name
        self.args_schema = schema or EXPECTED_SCHEMA

    def get_input_jsonschema(self) -> dict:
        return self.args_schema


class FakeMcpClient:
    def __init__(self, tools=None, error: Exception | None = None) -> None:
        self.tools = list(tools or [])
        self.error = error

    async def get_tools(self, *, server_name: str):
        if self.error is not None:
            raise self.error
        return self.tools


class RecordingClientFactory:
    def __init__(self, client: FakeMcpClient) -> None:
        self.client = client
        self.connections = None
        self.interceptors = None

    def __call__(self, connections, *, tool_interceptors):
        self.connections = connections
        self.interceptors = tool_interceptors
        return self.client


class McpAwardToolTest(unittest.IsolatedAsyncioTestCase):
    def settings(self, **overrides) -> Settings:
        values = {
            "award_detail_transport": "mcp",
            "award_detail_mcp_url": "http://127.0.0.1:8088/mcp",
        }
        values.update(overrides)
        return Settings(**values)

    async def test_discovers_only_allowlisted_tool_and_uses_bounded_connection(self):
        approved = FakeTool("get_award_detail")
        factory = RecordingClientFactory(
            FakeMcpClient([approved, FakeTool("future_write_tool")])
        )

        binding = await discover_award_detail_mcp_tool(
            self.settings(award_detail_mcp_call_timeout_seconds=2.5),
            client_factory=factory,
        )

        self.assertIs(approved, binding.tool)
        self.assertEqual(2, binding.discovered_tool_count)
        connection = factory.connections["java-business"]
        self.assertEqual("streamable_http", connection["transport"])
        self.assertEqual(2.5, connection["timeout"])
        self.assertEqual(1, len(factory.interceptors))

    async def test_rejects_missing_duplicate_and_drifted_tool(self):
        cases = [
            ([], "MCP_TOOL_MISSING"),
            (
                [FakeTool("get_award_detail"), FakeTool("get_award_detail")],
                "MCP_TOOL_DUPLICATED",
            ),
            (
                [
                    FakeTool(
                        "get_award_detail",
                        {
                            "type": "object",
                            "properties": {
                                "award_id": {
                                    "type": "integer",
                                    "minimum": 1,
                                    "maximum": JAVA_LONG_MAX,
                                },
                                "user_id": {"type": "integer"},
                            },
                            "required": ["award_id", "user_id"],
                            "additionalProperties": False,
                        },
                    )
                ],
                "MCP_CONTRACT_DRIFT",
            ),
            (
                [
                    FakeTool(
                        "get_award_detail",
                        {
                            "type": "object",
                            "properties": {
                                "award_id": {
                                    "type": "integer",
                                    "minimum": 2,
                                    "maximum": JAVA_LONG_MAX,
                                },
                            },
                            "required": ["award_id"],
                            "additionalProperties": False,
                        },
                    )
                ],
                "MCP_CONTRACT_DRIFT",
            ),
        ]
        for tools, expected_category in cases:
            with self.subTest(category=expected_category):
                with self.assertRaises(McpAwardToolInitializationError) as raised:
                    await discover_award_detail_mcp_tool(
                        self.settings(),
                        client_factory=RecordingClientFactory(FakeMcpClient(tools)),
                    )
                self.assertEqual(expected_category, raised.exception.category)

    async def test_reports_unavailable_endpoint_without_rest_fallback(self):
        with self.assertRaises(McpAwardToolInitializationError) as raised:
            await discover_award_detail_mcp_tool(
                self.settings(),
                client_factory=RecordingClientFactory(
                    FakeMcpClient(error=ConnectionError("offline"))
                ),
            )

        self.assertEqual("MCP_UNAVAILABLE", raised.exception.category)

    async def test_reports_discovery_timeout(self):
        class SlowClient(FakeMcpClient):
            async def get_tools(self, *, server_name: str):
                await asyncio.sleep(0.05)
                return []

        with self.assertRaises(McpAwardToolInitializationError) as raised:
            await discover_award_detail_mcp_tool(
                self.settings(
                    award_detail_mcp_initialization_timeout_seconds=0.001
                ),
                client_factory=RecordingClientFactory(SlowClient()),
            )

        self.assertEqual("MCP_DISCOVERY_TIMEOUT", raised.exception.category)

    async def test_mcp_interceptor_records_transport_and_business_code(self):
        interceptor = McpAwardTraceInterceptor()
        request = MCPToolCallRequest(
            name="get_award_detail",
            args={"award_id": 6},
            server_name="java-business",
        )
        result = CallToolResult(
            content=[],
            structuredContent={
                "success": False,
                "code": "AWARD_NOT_FOUND",
                "data": None,
                "message": "奖品不存在",
                "retryable": False,
            },
        )

        async def handler(actual_request):
            self.assertIs(request, actual_request)
            return result

        with capture_tool_trace("request-mcp") as session:
            actual = await interceptor(request, handler)

        self.assertIs(result, actual)
        event = session.as_dicts()[0]
        self.assertEqual("mcp", event["transport"])
        self.assertEqual("AWARD_NOT_FOUND", event["result_code"])
        self.assertEqual({"award_id": 6}, event["arguments"])

    async def test_remote_tool_replaces_only_local_award_tool(self):
        remote = FakeTool("get_award_detail")
        baseline = build_tools(FixtureBusinessApiClient("eligible"), 10)
        replaced = build_tools(
            FixtureBusinessApiClient("eligible"),
            10,
            award_detail_tool=remote,
        )

        baseline_names = [tool.name for tool in baseline]
        replaced_names = [tool.name for tool in replaced]
        self.assertEqual(baseline_names, replaced_names)
        self.assertEqual(1, replaced_names.count("get_award_detail"))
        self.assertIs(remote, replaced[replaced_names.index("get_award_detail")])

    async def test_internal_services_keep_using_rest_client_after_replacement(self):
        client = FixtureBusinessApiClient("eligible")
        tools = {
            tool.name: tool
            for tool in build_tools(
                client,
                10,
                award_detail_tool=FakeTool("get_award_detail"),
            )
        }

        tools["plan_points_for_award"].invoke(
            {"award_id": 6, "excluded_task_ids": []}
        )
        tools["recommend_awards"].invoke({"limit": 3})
        with bind_execution_context("user:10:session:mcp-boundary"):
            tools["save_redemption_goal"].invoke(
                {"award_id": 6, "target_date": "2027-01-01"}
            )
            tools["prepare_exchange"].invoke({"award_id": 6})

        called_methods = [call["method"] for call in client.calls]
        self.assertGreaterEqual(called_methods.count("get_award_detail"), 3)
        self.assertIn("list_awards", called_methods)
        self.assertIn("check_exchange_eligibility", called_methods)


if __name__ == "__main__":
    unittest.main()
