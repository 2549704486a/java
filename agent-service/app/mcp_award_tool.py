from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.interceptors import MCPToolCallResult

from app.config import Settings
from app.trace import execute_traced_async


MCP_SERVER_NAME = "java-business"
AWARD_DETAIL_TOOL_NAME = "get_award_detail"
JAVA_LONG_MAX = 9_223_372_036_854_775_807


class McpAwardToolInitializationError(RuntimeError):
    def __init__(self, category: str, message: str) -> None:
        super().__init__(message)
        self.category = category


@dataclass(frozen=True)
class McpAwardToolBinding:
    tool: BaseTool
    server_name: str
    discovered_tool_count: int


class McpAwardTraceInterceptor:
    async def __call__(self, request, handler) -> MCPToolCallResult:
        arguments = {"award_id": request.args.get("award_id")}
        return await execute_traced_async(
            request.name,
            arguments,
            lambda: handler(request),
            transport="mcp",
        )


async def discover_award_detail_mcp_tool(
    settings: Settings,
    *,
    client_factory=MultiServerMCPClient,
) -> McpAwardToolBinding:
    """发现并校验唯一允许进入用户 Agent 的 Java MCP Tool。"""
    if settings.award_detail_transport != "mcp":
        raise McpAwardToolInitializationError(
            "MCP_NOT_ENABLED",
            "仅在 AWARD_DETAIL_TRANSPORT=mcp 时初始化远程 Tool",
        )

    connection = {
        "transport": "streamable_http",
        "url": settings.award_detail_mcp_url,
        "timeout": settings.award_detail_mcp_call_timeout_seconds,
        "sse_read_timeout": settings.award_detail_mcp_call_timeout_seconds,
    }
    client = client_factory(
        {MCP_SERVER_NAME: connection},
        tool_interceptors=[McpAwardTraceInterceptor()],
    )
    try:
        tools = await asyncio.wait_for(
            client.get_tools(server_name=MCP_SERVER_NAME),
            timeout=settings.award_detail_mcp_initialization_timeout_seconds,
        )
    except TimeoutError as exc:
        raise McpAwardToolInitializationError(
            "MCP_DISCOVERY_TIMEOUT",
            "Java MCP Tool 发现超时",
        ) from exc
    except Exception as exc:
        raise McpAwardToolInitializationError(
            "MCP_UNAVAILABLE",
            f"Java MCP Tool 发现失败：{exc.__class__.__name__}",
        ) from exc

    matches = [tool for tool in tools if tool.name == AWARD_DETAIL_TOOL_NAME]
    if not matches:
        raise McpAwardToolInitializationError(
            "MCP_TOOL_MISSING",
            f"Java MCP Server 未暴露 {AWARD_DETAIL_TOOL_NAME}",
        )
    if len(matches) != 1:
        raise McpAwardToolInitializationError(
            "MCP_TOOL_DUPLICATED",
            f"Java MCP Server 重复暴露 {AWARD_DETAIL_TOOL_NAME}",
        )

    tool = matches[0]
    schema = tool.args_schema
    if not isinstance(schema, dict):
        schema = tool.get_input_jsonschema()
    if not _is_expected_award_schema(schema):
        raise McpAwardToolInitializationError(
            "MCP_CONTRACT_DRIFT",
            "get_award_detail 输入契约与预期不一致",
        )

    return McpAwardToolBinding(
        tool=tool,
        server_name=MCP_SERVER_NAME,
        discovered_tool_count=len(tools),
    )


def _is_expected_award_schema(schema: Any) -> bool:
    if not isinstance(schema, dict) or schema.get("type") != "object":
        return False
    properties = schema.get("properties")
    if not isinstance(properties, dict) or set(properties) != {"award_id"}:
        return False
    if set(schema.get("required", [])) != {"award_id"}:
        return False
    if schema.get("additionalProperties") is not False:
        return False

    award_id = properties["award_id"]
    if not isinstance(award_id, dict) or award_id.get("type") != "integer":
        return False
    minimum = award_id.get("minimum")
    exclusive_minimum = award_id.get("exclusiveMinimum")
    has_exact_minimum = (
        isinstance(minimum, (int, float))
        and not isinstance(minimum, bool)
        and minimum == 1
        and exclusive_minimum is None
    )
    has_exact_exclusive_minimum = (
        isinstance(exclusive_minimum, (int, float))
        and not isinstance(exclusive_minimum, bool)
        and exclusive_minimum == 0
        and minimum is None
    )
    domain_restrictions = {
        "exclusiveMaximum",
        "multipleOf",
        "enum",
        "const",
    }
    return (
        (has_exact_minimum or has_exact_exclusive_minimum)
        and award_id.get("maximum") == JAVA_LONG_MAX
        and domain_restrictions.isdisjoint(award_id)
    )
