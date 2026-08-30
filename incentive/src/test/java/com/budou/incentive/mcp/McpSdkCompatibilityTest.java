package com.budou.incentive.mcp;

import com.fasterxml.jackson.databind.ObjectMapper;
import io.modelcontextprotocol.json.McpJsonMapper;
import io.modelcontextprotocol.json.jackson2.JacksonMcpJsonMapper;
import io.modelcontextprotocol.server.McpServer;
import io.modelcontextprotocol.server.McpSyncServer;
import io.modelcontextprotocol.server.transport.HttpServletStreamableServerTransportProvider;
import io.modelcontextprotocol.spec.McpSchema;
import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

class McpSdkCompatibilityTest {

    @Test
    void shouldCreateAndCloseStreamableHttpServerWithBootManagedDependencies() {
        McpJsonMapper jsonMapper = new JacksonMcpJsonMapper(new ObjectMapper());
        HttpServletStreamableServerTransportProvider transport =
                HttpServletStreamableServerTransportProvider.builder()
                        .jsonMapper(jsonMapper)
                        .mcpEndpoint("/mcp")
                        .disallowDelete(true)
                        .maxRequestSize(64 * 1024)
                        .build();

        McpSchema.Tool tool = McpSchema.Tool.builder()
                .name("compatibility_probe")
                .description("Verifies that the MCP SDK can run with this application's dependency set.")
                .inputSchema(new McpSchema.JsonSchema(
                        "object",
                        Map.of("value", Map.of("type", "integer", "minimum", 1)),
                        List.of("value"),
                        false,
                        null,
                        null))
                .annotations(new McpSchema.ToolAnnotations(
                        "Compatibility probe", true, false, true, false, false))
                .build();

        McpSyncServer server = McpServer.sync(transport)
                .serverInfo("incentive-mcp-compatibility-probe", "0.1.0")
                .capabilities(McpSchema.ServerCapabilities.builder().tools(false).build())
                .jsonMapper(jsonMapper)
                .toolCall(tool, (exchange, request) -> McpSchema.CallToolResult.builder()
                        .addTextContent("ok")
                        .structuredContent(Map.of("success", true))
                        .build())
                .build();

        try {
            assertThat(server.listTools()).extracting(McpSchema.Tool::name)
                    .containsExactly("compatibility_probe");
        } finally {
            server.close();
        }
    }
}
