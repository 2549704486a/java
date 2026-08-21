package com.budou.incentive.controller;

import com.budou.incentive.dto.agent.AgentToolResponse;
import com.budou.incentive.service.AgentExchangeCommandService;
import lombok.extern.slf4j.Slf4j;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.regex.Pattern;

/**
 * Agent 写操作适配层。这里只把稳定协议映射到现有事务消息链路，不复制兑换逻辑。
 */
@RestController
@RequestMapping("agent/commands")
@Slf4j
public class AgentCommandController {

    private static final Pattern IDEMPOTENCY_KEY_PATTERN =
            Pattern.compile("^[A-Za-z0-9._:-]{1,128}$");

    private final AgentExchangeCommandService commandService;

    public AgentCommandController(AgentExchangeCommandService commandService) {
        this.commandService = commandService;
    }

    @PostMapping("users/{userId}/awards/{awardId}/exchange")
    public AgentToolResponse<Void> exchange(
            @PathVariable Long userId,
            @PathVariable Long awardId,
            @RequestHeader(value = "X-Request-ID", required = false) String requestId,
            @RequestHeader("Idempotency-Key") String idempotencyKey) {
        if (idempotencyKey == null || !IDEMPOTENCY_KEY_PATTERN.matcher(idempotencyKey).matches()) {
            return AgentToolResponse.fail(
                    "INVALID_IDEMPOTENCY_KEY",
                    "兑换确认凭证不合法",
                    false
            );
        }

        // 持久化幂等层先占位，再决定执行旧链路还是重放此前响应。
        AgentToolResponse<Void> response = commandService.exchange(userId, awardId, idempotencyKey);
        log.info(
                "agentExchangeCompleted requestId={} userId={} awardId={} resultCode={}",
                requestId, userId, awardId, response.code()
        );
        return response;
    }
}
