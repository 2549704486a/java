package com.budou.incentive.mcp;

import ch.qos.logback.classic.Logger;
import ch.qos.logback.classic.Level;
import ch.qos.logback.classic.spi.ILoggingEvent;
import ch.qos.logback.core.read.ListAppender;
import com.budou.incentive.dto.agent.AgentToolResponse;
import com.budou.incentive.dto.agent.AwardDetailView;
import com.budou.incentive.service.AgentQueryService;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.modelcontextprotocol.json.schema.jackson2.DefaultJsonSchemaValidator;
import io.modelcontextprotocol.spec.McpSchema;
import org.junit.jupiter.api.Test;
import org.slf4j.LoggerFactory;

import java.util.Date;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

class AwardQueryMcpToolTest {

    @Test
    void shouldLogOnlyProtocolSummaryInsteadOfFullAwardResponse() {
        AgentQueryService service = mock(AgentQueryService.class);
        ObjectMapper objectMapper = new ObjectMapper().findAndRegisterModules();
        AwardDetailView award = new AwardDetailView(
                6L,
                "不应出现在日志中的奖品名",
                "https://secret.example.test/cover.png",
                1,
                10,
                900,
                new Date(),
                new Date(),
                false);
        when(service.getAwardDetail(6L))
                .thenReturn(AgentToolResponse.ok("AWARD_FOUND", award, "奖品查询成功"));
        AwardQueryMcpTool tool = new AwardQueryMcpTool(
                service,
                objectMapper,
                new DefaultJsonSchemaValidator(objectMapper));

        Logger logger = (Logger) LoggerFactory.getLogger(AwardQueryMcpTool.class);
        Level previousLevel = logger.getLevel();
        logger.setLevel(Level.INFO);
        ListAppender<ILoggingEvent> appender = new ListAppender<>();
        appender.start();
        logger.addAppender(appender);
        try {
            tool.invoke(new McpSchema.CallToolRequest(
                    AwardQueryMcpTool.TOOL_NAME,
                    Map.of(AwardQueryMcpTool.AWARD_ID_ARGUMENT, 6)));
        } finally {
            logger.detachAppender(appender);
            logger.setLevel(previousLevel);
            appender.stop();
        }

        List<String> messages = appender.list.stream()
                .map(ILoggingEvent::getFormattedMessage)
                .toList();
        assertThat(messages).hasSize(1);
        assertThat(messages.get(0))
                .contains("callId=", "tool=get_award_detail", "code=AWARD_FOUND", "success=true", "elapsedMs=")
                .doesNotContain(award.name(), award.coverUrl(), "inventory", "requiredPoints");
    }
}
