package com.budou.incentive.controller;

import com.budou.incentive.dto.agent.AgentToolResponse;
import com.budou.incentive.service.UserAwardService;
import com.budou.incentive.utils.Result;
import com.budou.incentive.utils.ResultCodeEnum;
import lombok.extern.slf4j.Slf4j;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * Agent 写操作适配层。这里只把稳定协议映射到现有事务消息链路，不复制兑换逻辑。
 */
@RestController
@RequestMapping("agent/commands")
@Slf4j
public class AgentCommandController {

    private final UserAwardService userAwardService;

    public AgentCommandController(UserAwardService userAwardService) {
        this.userAwardService = userAwardService;
    }

    @PostMapping("users/{userId}/awards/{awardId}/exchange")
    public AgentToolResponse<Void> exchange(
            @PathVariable Long userId,
            @PathVariable Long awardId,
            @RequestHeader(value = "X-Request-ID", required = false) String requestId,
            @RequestHeader("Idempotency-Key") String idempotencyKey) {
        if (idempotencyKey == null || idempotencyKey.isBlank() || idempotencyKey.length() > 128) {
            return AgentToolResponse.fail(
                    "INVALID_IDEMPOTENCY_KEY",
                    "兑换确认凭证不合法",
                    false
            );
        }

        // Python 层已原子消费一次性凭证；这里仍执行旧链路的实时业务校验。
        Result<?> result = userAwardService.exchange(userId, awardId);
        if (result == null || result.getCode() == null) {
            log.warn(
                    "agentExchangeCompleted requestId={} userId={} awardId={} resultCode=EMPTY_RESULT",
                    requestId, userId, awardId
            );
            return AgentToolResponse.fail(
                    "EXCHANGE_REJECTED",
                    "兑换请求被业务系统拒绝",
                    false
            );
        }

        Integer code = result.getCode();
        log.info(
                "agentExchangeCompleted requestId={} userId={} awardId={} resultCode={}",
                requestId, userId, awardId, code
        );
        if (ResultCodeEnum.Query_Later.getCode().equals(code)) {
            return AgentToolResponse.ok(
                    "EXCHANGE_PROCESSING",
                    null,
                    "兑换请求已进入处理流程，请到订单页面查看最终结果"
            );
        }
        if (ResultCodeEnum.AWARD_REDEEMED.getCode().equals(code)) {
            return AgentToolResponse.fail(
                    "ALREADY_REDEEMED",
                    "该奖品已经兑换或已有兑换记录",
                    false
            );
        }
        return AgentToolResponse.fail(
                "EXCHANGE_REJECTED",
                rejectionMessage(code),
                false
        );
    }

    private String rejectionMessage(Integer code) {
        if (ResultCodeEnum.INSUFFICIENT_CURRENCY.getCode().equals(code)) {
            return "当前积分不足";
        }
        if (ResultCodeEnum.AWARD_EXPIRE.getCode().equals(code)) {
            return "兑换活动已经结束";
        }
        if (ResultCodeEnum.AWARD_NOT_STARTED.getCode().equals(code)) {
            return "兑换活动尚未开始";
        }
        if (ResultCodeEnum.TRANSACTION_SEND_FAILED.getCode().equals(code)) {
            return "事务消息发送失败，本次请求未受理";
        }
        return "兑换请求被业务系统拒绝";
    }
}
