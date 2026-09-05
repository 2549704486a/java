package com.budou.incentive.mcp;

import com.budou.incentive.dto.agent.AgentToolResponse;
import com.budou.incentive.dto.agent.AwardDetailView;
import com.budou.incentive.dto.agent.AwardOptionView;
import com.budou.incentive.dto.agent.ExchangeEligibilityView;
import com.budou.incentive.dto.agent.ExchangeRecordView;
import com.budou.incentive.dto.agent.TaskOptionView;
import com.budou.incentive.dto.agent.UserPointsView;
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
 * Thin MCP protocol adapter for existing user read-only Agent query services.
 */
final class AwardQueryMcpTool {

    static final String GET_USER_POINTS_TOOL_NAME = "get_user_points";
    static final String LIST_AVAILABLE_TASKS_TOOL_NAME = "list_available_tasks";
    static final String GET_AWARD_DETAIL_TOOL_NAME = "get_award_detail";
    static final String LIST_AWARDS_TOOL_NAME = "list_awards";
    static final String CHECK_EXCHANGE_ELIGIBILITY_TOOL_NAME = "check_exchange_eligibility";
    static final String LIST_EXCHANGE_RECORDS_TOOL_NAME = "list_exchange_records";
    static final String TOOL_NAME = GET_AWARD_DETAIL_TOOL_NAME;
    static final String USER_ID_ARGUMENT = "user_id";
    static final String AWARD_ID_ARGUMENT = "award_id";
    static final String REDEEMABLE_ONLY_ARGUMENT = "redeemable_only";

    private static final Logger log = LoggerFactory.getLogger(AwardQueryMcpTool.class);
    private static final TypeReference<Map<String, Object>> MAP_TYPE = new TypeReference<>() {
    };
    private static final Map<String, Object> POSITIVE_INTEGER_SCHEMA = Map.of(
            "type", "integer",
            "minimum", 1,
            "maximum", Long.MAX_VALUE);
    private static final Map<String, Object> BOOLEAN_SCHEMA = Map.of("type", "boolean");
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
    private static final Map<String, ToolSpec> TOOL_SPECS = Map.of(
            GET_USER_POINTS_TOOL_NAME, new ToolSpec(
                    GET_USER_POINTS_TOOL_NAME,
                    "查询用户积分",
                    "按受信用户 ID 查询实时积分。只读，用户身份由受信 MCP 客户端注入。",
                    objectSchema(Map.of(USER_ID_ARGUMENT, POSITIVE_INTEGER_SCHEMA), List.of(USER_ID_ARGUMENT))),
            LIST_AVAILABLE_TASKS_TOOL_NAME, new ToolSpec(
                    LIST_AVAILABLE_TASKS_TOOL_NAME,
                    "查询用户可用任务",
                    "按受信用户 ID 查询当前可用任务和已完成未领取任务。只读。",
                    objectSchema(Map.of(USER_ID_ARGUMENT, POSITIVE_INTEGER_SCHEMA), List.of(USER_ID_ARGUMENT))),
            GET_AWARD_DETAIL_TOOL_NAME, new ToolSpec(
                    GET_AWARD_DETAIL_TOOL_NAME,
                    "查询奖品详情",
                    "按奖品 ID 查询公开奖品详情。只读，不需要或接受用户身份参数。",
                    objectSchema(Map.of(AWARD_ID_ARGUMENT, POSITIVE_INTEGER_SCHEMA), List.of(AWARD_ID_ARGUMENT))),
            LIST_AWARDS_TOOL_NAME, new ToolSpec(
                    LIST_AWARDS_TOOL_NAME,
                    "查询奖品列表",
                    "按受信用户 ID 查询当前可兑换奖品列表，可选择只返回可兑换奖品。只读。",
                    objectSchema(
                            Map.of(
                                    USER_ID_ARGUMENT, POSITIVE_INTEGER_SCHEMA,
                                    REDEEMABLE_ONLY_ARGUMENT, BOOLEAN_SCHEMA),
                            List.of(USER_ID_ARGUMENT))),
            CHECK_EXCHANGE_ELIGIBILITY_TOOL_NAME, new ToolSpec(
                    CHECK_EXCHANGE_ELIGIBILITY_TOOL_NAME,
                    "查询兑换资格",
                    "按受信用户 ID 和奖品 ID 查询兑换资格、原因与积分差额。只读。",
                    objectSchema(
                            Map.of(
                                    USER_ID_ARGUMENT, POSITIVE_INTEGER_SCHEMA,
                                    AWARD_ID_ARGUMENT, POSITIVE_INTEGER_SCHEMA),
                            List.of(USER_ID_ARGUMENT, AWARD_ID_ARGUMENT))),
            LIST_EXCHANGE_RECORDS_TOOL_NAME, new ToolSpec(
                    LIST_EXCHANGE_RECORDS_TOOL_NAME,
                    "查询兑换记录",
                    "按受信用户 ID 查询兑换记录，可按奖品 ID 过滤。只读。",
                    objectSchema(
                            Map.of(
                                    USER_ID_ARGUMENT, POSITIVE_INTEGER_SCHEMA,
                                    AWARD_ID_ARGUMENT, POSITIVE_INTEGER_SCHEMA),
                            List.of(USER_ID_ARGUMENT))));

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

    List<McpSchema.Tool> definitions() {
        return List.of(
                definition(GET_USER_POINTS_TOOL_NAME),
                definition(LIST_AVAILABLE_TASKS_TOOL_NAME),
                definition(GET_AWARD_DETAIL_TOOL_NAME),
                definition(LIST_AWARDS_TOOL_NAME),
                definition(CHECK_EXCHANGE_ELIGIBILITY_TOOL_NAME),
                definition(LIST_EXCHANGE_RECORDS_TOOL_NAME));
    }

    McpSchema.Tool definition() {
        return definition(GET_AWARD_DETAIL_TOOL_NAME);
    }

    McpSchema.Tool definition(String toolName) {
        ToolSpec spec = TOOL_SPECS.get(toolName);
        if (spec == null) {
            throw new IllegalArgumentException("Unsupported MCP tool: " + toolName);
        }
        @SuppressWarnings("unchecked")
        Map<String, Object> properties = (Map<String, Object>) spec.inputSchema().get("properties");
        @SuppressWarnings("unchecked")
        List<String> required = (List<String>) spec.inputSchema().get("required");

        return McpSchema.Tool.builder()
                .name(spec.name())
                .title(spec.title())
                .description(spec.description())
                .inputSchema(new McpSchema.JsonSchema(
                        "object", properties, required, false, null, null))
                .outputSchema(OUTPUT_SCHEMA)
                .annotations(new McpSchema.ToolAnnotations(
                        spec.title(), true, false, true, false, false))
                .build();
    }

    McpSchema.CallToolResult invoke(McpSchema.CallToolRequest request) {
        long startedAt = System.nanoTime();
        String callId = UUID.randomUUID().toString();
        ToolSpec spec = TOOL_SPECS.get(request.name());
        if (spec == null) {
            logResult(callId, request.name(), "UNKNOWN_TOOL", false, startedAt);
            return protocolError("未知 MCP 工具：" + request.name());
        }
        Map<String, Object> arguments = request.arguments() == null ? Map.of() : request.arguments();
        JsonSchemaValidator.ValidationResponse validation =
                schemaValidator.validate(spec.inputSchema(), arguments);
        if (!validation.valid()) {
            logResult(callId, spec.name(), "INVALID_PARAMS", false, startedAt);
            return protocolError("参数不符合 " + spec.name() + " 的契约要求");
        }

        try {
            AgentToolResponse<?> response = dispatch(spec.name(), arguments);
            Map<String, Object> structuredResponse = objectMapper.convertValue(response, MAP_TYPE);
            logResult(callId, spec.name(), response.code(), response.success(), startedAt);
            return McpSchema.CallToolResult.builder()
                    .addTextContent(objectMapper.writeValueAsString(structuredResponse))
                    .structuredContent(structuredResponse)
                    .isError(false)
                    .build();
        } catch (JsonProcessingException | RuntimeException exception) {
            log.error("MCP callId={} tool={} code=INTERNAL_ERROR success=false elapsedMs={} errorType={}",
                    callId, spec.name(), elapsedMillis(startedAt), exception.getClass().getSimpleName());
            return protocolError("奖品查询暂时不可用");
        }
    }

    private AgentToolResponse<?> dispatch(String toolName, Map<String, Object> arguments) {
        return switch (toolName) {
            case GET_USER_POINTS_TOOL_NAME -> {
                Long userId = longArgument(arguments, USER_ID_ARGUMENT);
                AgentToolResponse<UserPointsView> response = agentQueryService.getUserPoints(userId);
                yield response;
            }
            case LIST_AVAILABLE_TASKS_TOOL_NAME -> {
                Long userId = longArgument(arguments, USER_ID_ARGUMENT);
                AgentToolResponse<List<TaskOptionView>> response = agentQueryService.listAvailableTasks(userId);
                yield response;
            }
            case GET_AWARD_DETAIL_TOOL_NAME -> {
                Long awardId = longArgument(arguments, AWARD_ID_ARGUMENT);
                AgentToolResponse<AwardDetailView> response = agentQueryService.getAwardDetail(awardId);
                yield response;
            }
            case LIST_AWARDS_TOOL_NAME -> {
                Long userId = longArgument(arguments, USER_ID_ARGUMENT);
                boolean redeemableOnly = Boolean.TRUE.equals(arguments.get(REDEEMABLE_ONLY_ARGUMENT));
                AgentToolResponse<List<AwardOptionView>> response =
                        agentQueryService.listAwards(userId, redeemableOnly);
                yield response;
            }
            case CHECK_EXCHANGE_ELIGIBILITY_TOOL_NAME -> {
                Long userId = longArgument(arguments, USER_ID_ARGUMENT);
                Long awardId = longArgument(arguments, AWARD_ID_ARGUMENT);
                AgentToolResponse<ExchangeEligibilityView> response =
                        agentQueryService.checkExchangeEligibility(userId, awardId);
                yield response;
            }
            case LIST_EXCHANGE_RECORDS_TOOL_NAME -> {
                Long userId = longArgument(arguments, USER_ID_ARGUMENT);
                Long awardId = arguments.containsKey(AWARD_ID_ARGUMENT)
                        ? longArgument(arguments, AWARD_ID_ARGUMENT)
                        : null;
                AgentToolResponse<List<ExchangeRecordView>> response =
                        agentQueryService.listExchangeRecords(userId, awardId);
                yield response;
            }
            default -> throw new IllegalArgumentException("Unsupported MCP tool: " + toolName);
        };
    }

    private Long longArgument(Map<String, Object> arguments, String argumentName) {
        return ((Number) arguments.get(argumentName)).longValue();
    }

    private McpSchema.CallToolResult protocolError(String message) {
        return McpSchema.CallToolResult.builder()
                .addTextContent(message)
                .isError(true)
                .build();
    }

    private void logResult(String callId, String toolName, String code, boolean success, long startedAt) {
        log.info("MCP callId={} tool={} code={} success={} elapsedMs={}",
                callId, toolName, code, success, elapsedMillis(startedAt));
    }

    private long elapsedMillis(long startedAt) {
        return TimeUnit.NANOSECONDS.toMillis(System.nanoTime() - startedAt);
    }

    private static Map<String, Object> objectSchema(Map<String, Object> properties, List<String> required) {
        return Map.of(
                "type", "object",
                "properties", properties,
                "required", required,
                "additionalProperties", false);
    }

    private record ToolSpec(String name, String title, String description, Map<String, Object> inputSchema) {
    }
}
