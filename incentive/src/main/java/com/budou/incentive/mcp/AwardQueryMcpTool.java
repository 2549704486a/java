package com.budou.incentive.mcp;

import com.budou.incentive.dto.agent.AgentToolResponse;
import com.budou.incentive.dto.agent.AwardDetailView;
import com.budou.incentive.service.AgentQueryService;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.modelcontextprotocol.json.schema.JsonSchemaValidator;
import io.modelcontextprotocol.spec.McpSchema;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.TimeUnit;

/**
 * Thin MCP protocol adapter for the existing award query service.
 */
final class AwardQueryMcpTool {

    static final String TOOL_NAME = "get_award_detail";
    static final String AWARD_ID_ARGUMENT = "award_id";

    private static final Logger log = LoggerFactory.getLogger(AwardQueryMcpTool.class);
    private static final TypeReference<Map<String, Object>> MAP_TYPE = new TypeReference<>() {
    };
    private static final Map<String, Object> INPUT_SCHEMA = Map.of(
            "type", "object",
            "properties", Map.of(
                    AWARD_ID_ARGUMENT, Map.of(
                            "type", "integer",
                            "minimum", 1,
                            "maximum", Long.MAX_VALUE)),
            "required", List.of(AWARD_ID_ARGUMENT),
            "additionalProperties", false);
    private static final Map<String, Object> OUTPUT_SCHEMA = Map.of(
            "type", "object",
            "properties", Map.of(
                    "success", Map.of("type", "boolean"),
                    "code", Map.of("type", "string"),
                    "data", Map.of("type", List.of("object", "null")),
                    "message", Map.of("type", "string"),
                    "retryable", Map.of("type", "boolean")),
            "required", List.of("success", "code", "data", "message", "retryable"),
            "additionalProperties", false);

    private final AgentQueryService agentQueryService;
    private final ObjectMapper objectMapper;
    private final JsonSchemaValidator schemaValidator;

    AwardQueryMcpTool(AgentQueryService agentQueryService,
                      ObjectMapper objectMapper,
                      JsonSchemaValidator schemaValidator) {
        this.agentQueryService = agentQueryService;
        this.objectMapper = objectMapper;
        this.schemaValidator = schemaValidator;
    }

    McpSchema.Tool definition() {
        @SuppressWarnings("unchecked")
        Map<String, Object> properties = (Map<String, Object>) INPUT_SCHEMA.get("properties");
        @SuppressWarnings("unchecked")
        List<String> required = (List<String>) INPUT_SCHEMA.get("required");

        return McpSchema.Tool.builder()
                .name(TOOL_NAME)
                .title("查询奖品详情")
                .description("按奖品 ID 查询公开奖品详情。只读，不需要或接受用户身份参数。")
                .inputSchema(new McpSchema.JsonSchema(
                        "object", properties, required, false, null, null))
                .outputSchema(OUTPUT_SCHEMA)
                .annotations(new McpSchema.ToolAnnotations(
                        "查询奖品详情", true, false, true, false, false))
                .build();
    }

    McpSchema.CallToolResult invoke(McpSchema.CallToolRequest request) {
        long startedAt = System.nanoTime();
        String callId = UUID.randomUUID().toString();
        JsonSchemaValidator.ValidationResponse validation =
                schemaValidator.validate(INPUT_SCHEMA, request.arguments());
        if (!validation.valid()) {
            logResult(callId, "INVALID_PARAMS", false, startedAt);
            return protocolError("参数不符合要求：award_id 必须是正整数，且不能包含其他参数");
        }

        try {
            long awardId = ((Number) request.arguments().get(AWARD_ID_ARGUMENT)).longValue();
            AgentToolResponse<AwardDetailView> response = agentQueryService.getAwardDetail(awardId);
            Map<String, Object> structuredResponse = objectMapper.convertValue(response, MAP_TYPE);
            logResult(callId, response.code(), response.success(), startedAt);
            return McpSchema.CallToolResult.builder()
                    .addTextContent(objectMapper.writeValueAsString(structuredResponse))
                    .structuredContent(structuredResponse)
                    .isError(false)
                    .build();
        } catch (JsonProcessingException | RuntimeException exception) {
            log.error("MCP callId={} tool={} code=INTERNAL_ERROR success=false elapsedMs={} errorType={}",
                    callId, TOOL_NAME, elapsedMillis(startedAt), exception.getClass().getSimpleName());
            return protocolError("奖品查询暂时不可用");
        }
    }

    private McpSchema.CallToolResult protocolError(String message) {
        return McpSchema.CallToolResult.builder()
                .addTextContent(message)
                .isError(true)
                .build();
    }

    private void logResult(String callId, String code, boolean success, long startedAt) {
        log.info("MCP callId={} tool={} code={} success={} elapsedMs={}",
                callId, TOOL_NAME, code, success, elapsedMillis(startedAt));
    }

    private long elapsedMillis(long startedAt) {
        return TimeUnit.NANOSECONDS.toMillis(System.nanoTime() - startedAt);
    }
}
