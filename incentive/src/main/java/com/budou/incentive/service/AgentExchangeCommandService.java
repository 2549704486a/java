package com.budou.incentive.service;

import com.budou.incentive.dao.mapper.AgentExchangeRequestMapper;
import com.budou.incentive.dao.model.AgentExchangeRequest;
import com.budou.incentive.dto.agent.AgentToolResponse;
import com.budou.incentive.utils.Result;
import com.budou.incentive.utils.ResultCodeEnum;
import lombok.extern.slf4j.Slf4j;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.stereotype.Service;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.Date;
import java.util.HexFormat;

/**
 * Agent 写入口的请求级幂等层。业务消费幂等仍由 idempotent_table 负责。
 */
@Service
@Slf4j
public class AgentExchangeCommandService {

    private static final String EXECUTING = "EXECUTING";
    private static final String COMPLETED = "COMPLETED";
    private static final String UNKNOWN = "UNKNOWN";
    private static final long EXECUTING_TIMEOUT_MILLIS = 30_000L;
    private static final String UNKNOWN_MESSAGE =
            "当前无法判断兑换请求是否已受理，请先到订单页面核对，不要立即重复兑换";

    private final AgentExchangeRequestMapper requestMapper;
    private final UserAwardService userAwardService;

    public AgentExchangeCommandService(
            AgentExchangeRequestMapper requestMapper,
            UserAwardService userAwardService
    ) {
        this.requestMapper = requestMapper;
        this.userAwardService = userAwardService;
    }

    public AgentToolResponse<Void> exchange(Long userId, Long awardId, String idempotencyKey) {
        String fingerprint = fingerprint(userId, awardId);

        // 先查询可减少正常重放时的唯一键冲突；真正的并发互斥仍由数据库唯一键保证。
        AgentExchangeRequest existing = requestMapper.selectByIdempotencyKey(idempotencyKey);
        if (existing != null) {
            return replay(existing, fingerprint);
        }

        try {
            requestMapper.insert(new AgentExchangeRequest(
                    null,
                    idempotencyKey,
                    fingerprint,
                    userId,
                    awardId,
                    EXECUTING,
                    null,
                    null,
                    null,
                    null,
                    null,
                    null
            ));
        } catch (DuplicateKeyException duplicate) {
            // 两个实例同时首次提交时，只有一个能占位，另一个读取胜出者的持久化状态。
            AgentExchangeRequest concurrent = requestMapper.selectByIdempotencyKey(idempotencyKey);
            if (concurrent == null) {
                return unknownResponse();
            }
            return replay(concurrent, fingerprint);
        }

        AgentToolResponse<Void> response;
        try {
            response = mapOldChainResult(userAwardService.exchange(userId, awardId));
        } catch (RuntimeException exception) {
            // 异常可能发生在消息已经到达 MQ 之后，因此只能记为未知，不能删除占位后重试。
            markUnknown(idempotencyKey);
            log.error(
                    "agentExchangeSubmissionUnknown idempotencyKey={} userId={} awardId={}",
                    idempotencyKey, userId, awardId, exception
            );
            return unknownResponse();
        }

        try {
            int updated = requestMapper.complete(
                    idempotencyKey,
                    response.success(),
                    response.code(),
                    response.message(),
                    response.retryable()
            );
            if (updated != 1) {
                log.error("agentExchangeIdempotencyCompleteFailed idempotencyKey={}", idempotencyKey);
                return unknownResponse();
            }
        } catch (RuntimeException exception) {
            // 业务调用已结束但响应没有可靠持久化时，同样禁止把请求当作可安全重放。
            markUnknown(idempotencyKey);
            log.error("agentExchangeIdempotencyPersistFailed idempotencyKey={}", idempotencyKey, exception);
            return unknownResponse();
        }
        return response;
    }

    private AgentToolResponse<Void> replay(AgentExchangeRequest existing, String fingerprint) {
        if (!fingerprint.equals(existing.getRequestFingerprint())) {
            return AgentToolResponse.fail(
                    "IDEMPOTENCY_KEY_CONFLICT",
                    "同一幂等键不能用于不同的兑换请求",
                    false
            );
        }
        if (COMPLETED.equals(existing.getStatus())) {
            boolean success = Boolean.TRUE.equals(existing.getResponseSuccess());
            boolean retryable = Boolean.TRUE.equals(existing.getResponseRetryable());
            if (success) {
                return AgentToolResponse.ok(
                        existing.getResponseCode(),
                        null,
                        existing.getResponseMessage()
                );
            }
            return AgentToolResponse.fail(
                    existing.getResponseCode(),
                    existing.getResponseMessage(),
                    retryable
            );
        }
        if (UNKNOWN.equals(existing.getStatus())) {
            return unknownResponse();
        }
        if (EXECUTING.equals(existing.getStatus())) {
            if (isStaleExecution(existing)) {
                // 占位进程可能已经崩溃；无法确定消息是否发出，只能转未知，不能抢占重做。
                markUnknown(existing.getIdempotencyKey());
                return unknownResponse();
            }
            return AgentToolResponse.fail(
                    "IDEMPOTENCY_REQUEST_IN_PROGRESS",
                    "相同兑换请求正在执行，请勿重复提交",
                    true
            );
        }
        log.error(
                "agentExchangeIdempotencyInvalidStatus idempotencyKey={} status={}",
                existing.getIdempotencyKey(), existing.getStatus()
        );
        return unknownResponse();
    }

    private boolean isStaleExecution(AgentExchangeRequest request) {
        Date referenceTime = request.getUpdateTime() != null
                ? request.getUpdateTime()
                : request.getCreateTime();
        return referenceTime == null
                || System.currentTimeMillis() - referenceTime.getTime() >= EXECUTING_TIMEOUT_MILLIS;
    }

    private void markUnknown(String idempotencyKey) {
        try {
            requestMapper.markUnknown(idempotencyKey, UNKNOWN_MESSAGE);
        } catch (RuntimeException persistException) {
            log.error("agentExchangeUnknownPersistFailed idempotencyKey={}", idempotencyKey, persistException);
        }
    }

    private AgentToolResponse<Void> mapOldChainResult(Result<?> result) {
        if (result == null || result.getCode() == null) {
            return AgentToolResponse.fail(
                    "EXCHANGE_REJECTED",
                    "兑换请求被业务系统拒绝",
                    false
            );
        }

        Integer code = result.getCode();
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

    private AgentToolResponse<Void> unknownResponse() {
        return AgentToolResponse.fail("SUBMISSION_UNKNOWN", UNKNOWN_MESSAGE, false);
    }

    private String fingerprint(Long userId, Long awardId) {
        String canonicalRequest = "userId=" + userId + "&awardId=" + awardId;
        try {
            byte[] digest = MessageDigest.getInstance("SHA-256")
                    .digest(canonicalRequest.getBytes(StandardCharsets.UTF_8));
            return HexFormat.of().formatHex(digest);
        } catch (NoSuchAlgorithmException exception) {
            throw new IllegalStateException("SHA-256 is unavailable", exception);
        }
    }
}
