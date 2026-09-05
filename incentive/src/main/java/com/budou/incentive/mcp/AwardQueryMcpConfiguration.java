package com.budou.incentive.mcp;

import com.budou.incentive.service.AgentQueryService;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.modelcontextprotocol.json.McpJsonMapper;
import io.modelcontextprotocol.json.jackson2.JacksonMcpJsonMapper;
import io.modelcontextprotocol.json.schema.JsonSchemaValidator;
import io.modelcontextprotocol.json.schema.jackson2.DefaultJsonSchemaValidator;
import io.modelcontextprotocol.server.McpServer;
import io.modelcontextprotocol.server.McpSyncServer;
import io.modelcontextprotocol.server.transport.DefaultServerTransportSecurityValidator;
import io.modelcontextprotocol.server.transport.HttpServletStreamableServerTransportProvider;
import io.modelcontextprotocol.spec.McpSchema;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.boot.web.servlet.FilterRegistrationBean;
import org.springframework.boot.web.servlet.ServletRegistrationBean;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.core.Ordered;
import org.springframework.web.filter.OncePerRequestFilter;

import java.io.IOException;
import java.net.InetAddress;
import java.net.UnknownHostException;
import java.time.Duration;
import java.util.List;

@Configuration(proxyBeanMethods = false)
@ConditionalOnProperty(prefix = "agent.mcp", name = "enabled", havingValue = "true")
public class AwardQueryMcpConfiguration {

    static final String MCP_ENDPOINT = "/mcp";
    private static final int MAX_REQUEST_SIZE = 64 * 1024;

    @Bean
    McpJsonMapper awardQueryMcpJsonMapper(ObjectMapper objectMapper) {
        return new JacksonMcpJsonMapper(objectMapper.copy());
    }

    @Bean
    JsonSchemaValidator awardQueryMcpSchemaValidator(ObjectMapper objectMapper) {
        return new DefaultJsonSchemaValidator(objectMapper.copy());
    }

    @Bean
    AwardQueryMcpTool awardQueryMcpTool(AgentQueryService agentQueryService,
                                       ObjectMapper objectMapper,
                                       JsonSchemaValidator schemaValidator) {
        return new AwardQueryMcpTool(agentQueryService, objectMapper, schemaValidator);
    }

    @Bean
    HttpServletStreamableServerTransportProvider awardQueryMcpTransport(McpJsonMapper jsonMapper) {
        DefaultServerTransportSecurityValidator securityValidator =
                DefaultServerTransportSecurityValidator.builder()
                        .allowedOrigins(List.of(
                                "http://localhost:*",
                                "http://127.0.0.1:*",
                                "http://[::1]:*"))
                        .allowedHosts(List.of(
                                "localhost:*",
                                "127.0.0.1:*",
                                "[::1]:*"))
                        .build();

        return HttpServletStreamableServerTransportProvider.builder()
                .jsonMapper(jsonMapper)
                .mcpEndpoint(MCP_ENDPOINT)
                .securityValidator(securityValidator)
                // DELETE closes an MCP session; it does not mutate award data.
                .disallowDelete(false)
                .maxRequestSize(MAX_REQUEST_SIZE)
                .build();
    }

    @Bean
    ServletRegistrationBean<HttpServletStreamableServerTransportProvider> awardQueryMcpServlet(
            HttpServletStreamableServerTransportProvider transport) {
        ServletRegistrationBean<HttpServletStreamableServerTransportProvider> registration =
                new ServletRegistrationBean<>(transport, MCP_ENDPOINT);
        registration.setName("awardQueryMcpServlet");
        registration.setLoadOnStartup(1);
        registration.setAsyncSupported(true);
        return registration;
    }

    @Bean
    FilterRegistrationBean<OncePerRequestFilter> awardQueryMcpLoopbackFilter() {
        FilterRegistrationBean<OncePerRequestFilter> registration =
                new FilterRegistrationBean<>(new LoopbackOnlyFilter());
        registration.setName("awardQueryMcpLoopbackFilter");
        registration.addUrlPatterns(MCP_ENDPOINT);
        registration.setAsyncSupported(true);
        registration.setOrder(Ordered.HIGHEST_PRECEDENCE);
        return registration;
    }

    @Bean(destroyMethod = "close")
    McpSyncServer awardQueryMcpServer(HttpServletStreamableServerTransportProvider transport,
                                     McpJsonMapper jsonMapper,
                                     JsonSchemaValidator schemaValidator,
                                     AwardQueryMcpTool tool) {
        var server = McpServer.sync(transport)
                .serverInfo("incentive-award-query", "0.1.0")
                .instructions("提供用户 Agent 所需的受控只读业务查询；身份参数仅供受信客户端注入。")
                .requestTimeout(Duration.ofSeconds(5))
                .capabilities(McpSchema.ServerCapabilities.builder().tools(false).build())
                .jsonMapper(jsonMapper)
                .jsonSchemaValidator(schemaValidator);
        for (McpSchema.Tool definition : tool.definitions()) {
            server.toolCall(definition, (exchange, request) -> tool.invoke(request));
        }
        return server.build();
    }

    static final class LoopbackOnlyFilter extends OncePerRequestFilter {

        @Override
        protected void doFilterInternal(HttpServletRequest request,
                                        HttpServletResponse response,
                                        FilterChain filterChain) throws ServletException, IOException {
            if (!isLoopbackAddress(request.getRemoteAddr())) {
                response.sendError(HttpServletResponse.SC_FORBIDDEN, "MCP endpoint is local-only");
                return;
            }
            filterChain.doFilter(request, response);
        }

        private boolean isLoopbackAddress(String remoteAddress) {
            try {
                return InetAddress.getByName(remoteAddress).isLoopbackAddress();
            } catch (UnknownHostException exception) {
                return false;
            }
        }
    }
}
