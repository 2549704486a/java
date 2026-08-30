package com.budou.incentive.mcp;

import com.budou.incentive.service.AgentQueryService;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.modelcontextprotocol.server.McpSyncServer;
import io.modelcontextprotocol.server.transport.HttpServletStreamableServerTransportProvider;
import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.runner.WebApplicationContextRunner;
import org.springframework.boot.web.servlet.ServletRegistrationBean;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;

class AwardQueryMcpConfigurationTest {

    private final WebApplicationContextRunner contextRunner = new WebApplicationContextRunner()
            .withUserConfiguration(AwardQueryMcpConfiguration.class)
            .withBean(ObjectMapper.class, ObjectMapper::new)
            .withBean(AgentQueryService.class, () -> mock(AgentQueryService.class));

    @Test
    void shouldNotRegisterMcpEndpointByDefault() {
        contextRunner.run(context -> {
            assertThat(context).doesNotHaveBean(McpSyncServer.class);
            assertThat(context).doesNotHaveBean(HttpServletStreamableServerTransportProvider.class);
            assertThat(context).doesNotHaveBean("awardQueryMcpServlet");
        });
    }

    @Test
    void shouldRegisterMcpEndpointOnlyWhenExplicitlyEnabled() {
        contextRunner
                .withPropertyValues("agent.mcp.enabled=true")
                .run(context -> {
                    assertThat(context).hasSingleBean(McpSyncServer.class);
                    assertThat(context).hasSingleBean(HttpServletStreamableServerTransportProvider.class);
                    assertThat(context).getBean("awardQueryMcpServlet")
                            .isInstanceOf(ServletRegistrationBean.class);
                });
    }
}
