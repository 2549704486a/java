package com.budou.incentive.mcp;

import com.budou.incentive.dto.agent.AgentToolResponse;
import com.budou.incentive.dto.agent.AwardDetailView;
import com.budou.incentive.dto.agent.AwardOptionView;
import com.budou.incentive.dto.agent.ExchangeEligibilityView;
import com.budou.incentive.dto.agent.ExchangeRecordView;
import com.budou.incentive.dto.agent.TaskOptionView;
import com.budou.incentive.dto.agent.UserPointsView;
import com.budou.incentive.controller.AgentQueryController;
import com.budou.incentive.service.AgentQueryService;
import com.budou.incentive.service.UserNotificationService;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.JsonNode;
import io.modelcontextprotocol.client.McpClient;
import io.modelcontextprotocol.client.McpSyncClient;
import io.modelcontextprotocol.client.transport.HttpClientStreamableHttpTransport;
import io.modelcontextprotocol.spec.McpSchema;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.BeforeEach;
import org.springframework.boot.SpringBootConfiguration;
import org.springframework.boot.autoconfigure.EnableAutoConfiguration;
import org.springframework.boot.autoconfigure.jdbc.DataSourceAutoConfiguration;
import org.springframework.boot.autoconfigure.orm.jpa.HibernateJpaAutoConfiguration;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.boot.test.web.client.TestRestTemplate;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Import;

import java.time.Duration;
import java.util.Date;
import java.util.ArrayList;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.TimeUnit;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.reset;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@SpringBootTest(
        classes = AwardQueryMcpProtocolTest.TestApplication.class,
        webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT,
        properties = {
                "agent.mcp.enabled=true",
                "debug=false",
                "logging.level.root=WARN"
        })
class AwardQueryMcpProtocolTest {

    private static final TypeReference<Map<String, Object>> MAP_TYPE = new TypeReference<>() {
    };

    @LocalServerPort
    private int port;

    @Autowired
    private AgentQueryService service;

    @Autowired
    private ObjectMapper objectMapper;

    @Autowired
    private TestRestTemplate restTemplate;

    @BeforeEach
    void resetServiceFixture() {
        reset(service);
    }

    @Test
    void shouldExposeApprovedUserReadToolsAndPreserveRestBusinessEnvelope() throws Exception {
        Date startedAt = new Date(1_700_000_000_000L);
        Date endedAt = new Date(1_800_000_000_000L);
        AwardDetailView award = new AwardDetailView(
                6L,
                "智能手环",
                "https://example.test/award-6.png",
                1,
                60,
                900,
                startedAt,
                endedAt,
                false);
        AgentToolResponse<UserPointsView> pointsExpected =
                AgentToolResponse.ok("POINTS_FOUND", new UserPointsView(10L, 1200), "积分查询成功");
        AgentToolResponse<List<TaskOptionView>> tasksExpected =
                AgentToolResponse.ok("TASKS_FOUND", List.of(
                        new TaskOptionView(1L, "签到", 10, startedAt, endedAt, 1, "每日签到", "AVAILABLE"),
                        new TaskOptionView(2L, "分享", 30, startedAt, endedAt, 2, "分享活动", "COMPLETED_UNCLAIMED")),
                        "可用任务查询成功");
        AgentToolResponse<AwardDetailView> awardExpected =
                AgentToolResponse.ok("AWARD_FOUND", award, "奖品查询成功");
        AgentToolResponse<AwardDetailView> notFound =
                AgentToolResponse.fail("AWARD_NOT_FOUND", "奖品不存在", false);
        AgentToolResponse<List<AwardOptionView>> awardsExpected =
                AgentToolResponse.ok("AWARDS_FOUND", List.of(
                        new AwardOptionView(award, true, 0, "ELIGIBLE")),
                        "奖品列表查询成功");
        AgentToolResponse<ExchangeEligibilityView> eligibilityExpected =
                AgentToolResponse.ok("ELIGIBLE",
                        new ExchangeEligibilityView(10L, 6L, true, "ELIGIBLE",
                                "当前满足兑换条件", 1200, 900, 0),
                        "当前满足兑换条件");
        AgentToolResponse<List<ExchangeRecordView>> recordsExpected =
                AgentToolResponse.ok("EXCHANGE_RECORDS_FOUND", List.of(
                        new ExchangeRecordView(101L, 6L, "智能手环", "SUCCESS",
                                "兑换成功", startedAt, endedAt)),
                        "兑换记录查询成功");
        when(service.getUserPoints(10L)).thenReturn(pointsExpected);
        when(service.listAvailableTasks(10L)).thenReturn(tasksExpected);
        when(service.getAwardDetail(6L)).thenReturn(awardExpected);
        when(service.getAwardDetail(999L)).thenReturn(notFound);
        when(service.listAwards(10L, true)).thenReturn(awardsExpected);
        when(service.checkExchangeEligibility(10L, 6L)).thenReturn(eligibilityExpected);
        when(service.listExchangeRecords(10L, 6L)).thenReturn(recordsExpected);

        HttpClientStreamableHttpTransport transport = HttpClientStreamableHttpTransport
                .builder("http://127.0.0.1:" + port)
                .endpoint(AwardQueryMcpConfiguration.MCP_ENDPOINT)
                .connectTimeout(Duration.ofSeconds(3))
                .maxResponseSize(64 * 1024)
                .build();

        try (McpSyncClient client = McpClient.sync(transport)
                .clientInfo(new McpSchema.Implementation("incentive-mcp-test", "0.1.0"))
                .requestTimeout(Duration.ofSeconds(5))
                .initializationTimeout(Duration.ofSeconds(5))
                .build()) {
            McpSchema.InitializeResult initialization = client.initialize();
            assertThat(initialization.serverInfo().name()).isEqualTo("incentive-award-query");

            McpSchema.ListToolsResult tools = client.listTools();
            Map<String, McpSchema.Tool> toolsByName = new LinkedHashMap<>();
            tools.tools().forEach(tool -> toolsByName.put(tool.name(), tool));
            assertThat(toolsByName.keySet()).containsExactly(
                    AwardQueryMcpTool.GET_USER_POINTS_TOOL_NAME,
                    AwardQueryMcpTool.LIST_AVAILABLE_TASKS_TOOL_NAME,
                    AwardQueryMcpTool.GET_AWARD_DETAIL_TOOL_NAME,
                    AwardQueryMcpTool.LIST_AWARDS_TOOL_NAME,
                    AwardQueryMcpTool.CHECK_EXCHANGE_ELIGIBILITY_TOOL_NAME,
                    AwardQueryMcpTool.LIST_EXCHANGE_RECORDS_TOOL_NAME);
            assertRequiredProperties(toolsByName.get(AwardQueryMcpTool.GET_USER_POINTS_TOOL_NAME),
                    List.of(AwardQueryMcpTool.USER_ID_ARGUMENT));
            assertRequiredProperties(toolsByName.get(AwardQueryMcpTool.LIST_AVAILABLE_TASKS_TOOL_NAME),
                    List.of(AwardQueryMcpTool.USER_ID_ARGUMENT));
            assertRequiredProperties(toolsByName.get(AwardQueryMcpTool.GET_AWARD_DETAIL_TOOL_NAME),
                    List.of(AwardQueryMcpTool.AWARD_ID_ARGUMENT));
            assertRequiredProperties(toolsByName.get(AwardQueryMcpTool.LIST_AWARDS_TOOL_NAME),
                    List.of(AwardQueryMcpTool.USER_ID_ARGUMENT),
                    AwardQueryMcpTool.REDEEMABLE_ONLY_ARGUMENT);
            assertRequiredProperties(toolsByName.get(AwardQueryMcpTool.CHECK_EXCHANGE_ELIGIBILITY_TOOL_NAME),
                    List.of(AwardQueryMcpTool.USER_ID_ARGUMENT, AwardQueryMcpTool.AWARD_ID_ARGUMENT));
            assertRequiredProperties(toolsByName.get(AwardQueryMcpTool.LIST_EXCHANGE_RECORDS_TOOL_NAME),
                    List.of(AwardQueryMcpTool.USER_ID_ARGUMENT),
                    AwardQueryMcpTool.AWARD_ID_ARGUMENT);

            assertMcpMatchesRest(client,
                    AwardQueryMcpTool.GET_USER_POINTS_TOOL_NAME,
                    Map.of(AwardQueryMcpTool.USER_ID_ARGUMENT, 10),
                    "/agent/query/users/10/points");
            assertMcpMatchesRest(client,
                    AwardQueryMcpTool.LIST_AVAILABLE_TASKS_TOOL_NAME,
                    Map.of(AwardQueryMcpTool.USER_ID_ARGUMENT, 10),
                    "/agent/query/users/10/tasks");

            McpSchema.CallToolResult foundResult = client.callTool(new McpSchema.CallToolRequest(
                    AwardQueryMcpTool.GET_AWARD_DETAIL_TOOL_NAME,
                    Map.of(AwardQueryMcpTool.AWARD_ID_ARGUMENT, 6)));
            JsonNode foundJson = toJson(foundResult);
            JsonNode foundRestJson = objectMapper.readTree(restTemplate.getForObject(
                    "/agent/query/awards/6", String.class));

            assertThat(foundResult.isError()).isFalse();
            assertThat(foundJson).isEqualTo(foundRestJson);

            McpSchema.CallToolResult notFoundResult = client.callTool(new McpSchema.CallToolRequest(
                    AwardQueryMcpTool.GET_AWARD_DETAIL_TOOL_NAME,
                    Map.of(AwardQueryMcpTool.AWARD_ID_ARGUMENT, 999)));
            JsonNode notFoundJson = toJson(notFoundResult);
            JsonNode notFoundRestJson = objectMapper.readTree(restTemplate.getForObject(
                    "/agent/query/awards/999", String.class));

            assertThat(notFoundResult.isError()).isFalse();
            assertThat(notFoundJson).isEqualTo(notFoundRestJson);

            assertMcpMatchesRest(client,
                    AwardQueryMcpTool.LIST_AWARDS_TOOL_NAME,
                    Map.of(
                            AwardQueryMcpTool.USER_ID_ARGUMENT, 10,
                            AwardQueryMcpTool.REDEEMABLE_ONLY_ARGUMENT, true),
                    "/agent/query/users/10/awards?redeemableOnly=true");
            assertMcpMatchesRest(client,
                    AwardQueryMcpTool.CHECK_EXCHANGE_ELIGIBILITY_TOOL_NAME,
                    Map.of(
                            AwardQueryMcpTool.USER_ID_ARGUMENT, 10,
                            AwardQueryMcpTool.AWARD_ID_ARGUMENT, 6),
                    "/agent/query/users/10/awards/6/eligibility");
            assertMcpMatchesRest(client,
                    AwardQueryMcpTool.LIST_EXCHANGE_RECORDS_TOOL_NAME,
                    Map.of(
                            AwardQueryMcpTool.USER_ID_ARGUMENT, 10,
                            AwardQueryMcpTool.AWARD_ID_ARGUMENT, 6),
                    "/agent/query/users/10/exchanges?awardId=6");

            McpSchema.CallToolResult invalidResult = client.callTool(new McpSchema.CallToolRequest(
                    AwardQueryMcpTool.GET_AWARD_DETAIL_TOOL_NAME,
                    Map.of(AwardQueryMcpTool.AWARD_ID_ARGUMENT, 0)));
            assertThat(invalidResult.isError()).isTrue();
            assertThat(invalidResult.content().get(0).toString()).contains("award_id");

            McpSchema.CallToolResult identityArgumentResult = client.callTool(new McpSchema.CallToolRequest(
                    AwardQueryMcpTool.GET_AWARD_DETAIL_TOOL_NAME,
                    Map.of(
                            AwardQueryMcpTool.AWARD_ID_ARGUMENT, 6,
                            "user_id", 10)));
            assertThat(identityArgumentResult.isError()).isTrue();

            verify(service, times(2)).getUserPoints(10L);
            verify(service, times(2)).listAvailableTasks(10L);
            verify(service, times(2)).getAwardDetail(6L);
            verify(service, times(2)).getAwardDetail(999L);
            verify(service, times(2)).listAwards(10L, true);
            verify(service, times(2)).checkExchangeEligibility(10L, 6L);
            verify(service, times(2)).listExchangeRecords(10L, 6L);
            verify(service, never()).getAwardDetail(0L);
        }
    }

    @Test
    void shouldMeasureRestAndMcpWithStableLocalConnections() throws Exception {
        AwardDetailView award = new AwardDetailView(
                6L, "智能手环", "/award-6.png", 1, 60, 900,
                new Date(1_700_000_000_000L), new Date(1_800_000_000_000L), false);
        AgentToolResponse<AwardDetailView> expected =
                AgentToolResponse.ok("AWARD_FOUND", award, "奖品查询成功");
        when(service.getAwardDetail(6L)).thenReturn(expected);
        JsonNode expectedJson = objectMapper.readTree(objectMapper.writeValueAsBytes(expected));

        HttpClientStreamableHttpTransport transport = HttpClientStreamableHttpTransport
                .builder("http://127.0.0.1:" + port)
                .endpoint(AwardQueryMcpConfiguration.MCP_ENDPOINT)
                .connectTimeout(Duration.ofSeconds(3))
                .maxResponseSize(64 * 1024)
                .build();

        try (McpSyncClient client = McpClient.sync(transport)
                .clientInfo(new McpSchema.Implementation("incentive-mcp-comparison", "0.1.0"))
                .requestTimeout(Duration.ofSeconds(5))
                .initializationTimeout(Duration.ofSeconds(5))
                .build()) {
            client.initialize();
            for (int i = 0; i < 5; i++) {
                queryRestAward();
                queryMcpAward(client);
            }

            int samples = 30;
            int restSuccesses = 0;
            int mcpSuccesses = 0;
            int contractMatches = 0;
            List<Long> restMicros = new ArrayList<>(samples);
            List<Long> mcpMicros = new ArrayList<>(samples);

            for (int i = 0; i < samples; i++) {
                long restStarted = System.nanoTime();
                JsonNode restJson = queryRestAward();
                restMicros.add(elapsedMicros(restStarted));

                long mcpStarted = System.nanoTime();
                JsonNode mcpJson = queryMcpAward(client);
                mcpMicros.add(elapsedMicros(mcpStarted));

                restSuccesses += expectedJson.equals(restJson) ? 1 : 0;
                mcpSuccesses += expectedJson.equals(mcpJson) ? 1 : 0;
                contractMatches += restJson.equals(mcpJson) ? 1 : 0;
            }

            assertThat(restSuccesses).isEqualTo(samples);
            assertThat(mcpSuccesses).isEqualTo(samples);
            assertThat(contractMatches).isEqualTo(samples);
            System.out.printf(
                    "MCP_REST_COMPARISON samples=%d restSuccessRate=%.2f mcpSuccessRate=%.2f "
                            + "contractMatchRate=%.2f restAvgMs=%.3f restP95Ms=%.3f "
                            + "mcpAvgMs=%.3f mcpP95Ms=%.3f%n",
                    samples,
                    rate(restSuccesses, samples),
                    rate(mcpSuccesses, samples),
                    rate(contractMatches, samples),
                    averageMillis(restMicros),
                    percentile95Millis(restMicros),
                    averageMillis(mcpMicros),
                    percentile95Millis(mcpMicros));
        }
    }

    private JsonNode toJson(McpSchema.CallToolResult result) throws Exception {
        Map<String, Object> structured = objectMapper.convertValue(result.structuredContent(), MAP_TYPE);
        // JSON transport does not retain Java's Integer/Long wrapper distinction.
        return objectMapper.readTree(objectMapper.writeValueAsBytes(structured));
    }

    private void assertRequiredProperties(McpSchema.Tool tool, List<String> required, String... optional) {
        assertThat(tool).isNotNull();
        List<String> expectedProperties = new ArrayList<>(required);
        expectedProperties.addAll(List.of(optional));
        assertThat(tool.inputSchema().required()).containsExactlyElementsOf(required);
        assertThat(tool.inputSchema().properties()).containsOnlyKeys(expectedProperties.toArray(String[]::new));
    }

    private void assertMcpMatchesRest(McpSyncClient client,
                                      String toolName,
                                      Map<String, Object> arguments,
                                      String restPath) throws Exception {
        McpSchema.CallToolResult mcpResult = client.callTool(new McpSchema.CallToolRequest(toolName, arguments));
        JsonNode mcpJson = toJson(mcpResult);
        JsonNode restJson = objectMapper.readTree(restTemplate.getForObject(restPath, String.class));

        assertThat(mcpResult.isError()).isFalse();
        assertThat(mcpJson).isEqualTo(restJson);
    }

    private JsonNode queryRestAward() throws Exception {
        return objectMapper.readTree(restTemplate.getForObject(
                "/agent/query/awards/6", String.class));
    }

    private JsonNode queryMcpAward(McpSyncClient client) throws Exception {
        return toJson(client.callTool(new McpSchema.CallToolRequest(
                AwardQueryMcpTool.TOOL_NAME,
                Map.of(AwardQueryMcpTool.AWARD_ID_ARGUMENT, 6))));
    }

    private long elapsedMicros(long startedAt) {
        return TimeUnit.NANOSECONDS.toMicros(System.nanoTime() - startedAt);
    }

    private double rate(int count, int total) {
        return (double) count / total;
    }

    private double averageMillis(List<Long> micros) {
        return micros.stream().mapToLong(Long::longValue).average().orElse(0.0) / 1_000.0;
    }

    private double percentile95Millis(List<Long> micros) {
        List<Long> sorted = new ArrayList<>(micros);
        Collections.sort(sorted);
        int index = Math.max(0, (int) Math.ceil(sorted.size() * 0.95) - 1);
        return sorted.get(index) / 1_000.0;
    }

    @SpringBootConfiguration
    @EnableAutoConfiguration(exclude = {
            DataSourceAutoConfiguration.class,
            HibernateJpaAutoConfiguration.class
    })
    @Import(AwardQueryMcpConfiguration.class)
    static class TestApplication {

        @Bean
        ObjectMapper objectMapper() {
            return new ObjectMapper().findAndRegisterModules();
        }

        @Bean
        AgentQueryService agentQueryService() {
            return mock(AgentQueryService.class);
        }

        @Bean
        UserNotificationService userNotificationService() {
            return mock(UserNotificationService.class);
        }

        @Bean
        AgentQueryController agentQueryController(AgentQueryService queryService,
                                                  UserNotificationService notificationService) {
            return new AgentQueryController(queryService, notificationService);
        }
    }
}
