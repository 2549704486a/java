package com.budou.incentive.service;

import com.budou.incentive.dao.mapper.AgentExchangeRequestMapper;
import com.budou.incentive.dao.model.AgentExchangeRequest;
import com.budou.incentive.dto.agent.AgentToolResponse;
import com.budou.incentive.utils.Result;
import com.budou.incentive.utils.ResultCodeEnum;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.dao.DuplicateKeyException;

import java.util.Date;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class AgentExchangeCommandServiceTest {

    @Mock
    private AgentExchangeRequestMapper requestMapper;

    @Mock
    private UserAwardService userAwardService;

    private AgentExchangeCommandService service;

    @BeforeEach
    void setUp() {
        service = new AgentExchangeCommandService(requestMapper, userAwardService);
    }

    @Test
    void shouldPersistAndReturnFirstAcceptedRequest() {
        when(requestMapper.selectByIdempotencyKey("key-001")).thenReturn(null);
        when(requestMapper.insert(any(AgentExchangeRequest.class))).thenReturn(1);
        when(userAwardService.exchange(10L, 6L))
                .thenReturn(Result.build(null, ResultCodeEnum.Query_Later));
        when(requestMapper.complete(
                "key-001",
                true,
                "EXCHANGE_PROCESSING",
                "兑换请求已进入处理流程，请到订单页面查看最终结果",
                false
        )).thenReturn(1);

        AgentToolResponse<Void> response = service.exchange(10L, 6L, "key-001");

        assertTrue(response.success());
        assertEquals("EXCHANGE_PROCESSING", response.code());
        verify(userAwardService).exchange(10L, 6L);
        verify(requestMapper).complete(
                "key-001",
                true,
                "EXCHANGE_PROCESSING",
                "兑换请求已进入处理流程，请到订单页面查看最终结果",
                false
        );
    }

    @Test
    void shouldReplayCompletedResponseWithoutCallingOldChain() {
        AgentExchangeRequest existing = completedRequest(
                "key-002",
                10L,
                6L,
                true,
                "EXCHANGE_PROCESSING",
                "已受理"
        );
        when(requestMapper.selectByIdempotencyKey("key-002")).thenReturn(existing);

        AgentToolResponse<Void> response = service.exchange(10L, 6L, "key-002");

        assertTrue(response.success());
        assertEquals("EXCHANGE_PROCESSING", response.code());
        assertEquals("已受理", response.message());
        verify(userAwardService, never()).exchange(any(), any());
        verify(requestMapper, never()).insert(any());
    }

    @Test
    void shouldRejectSameKeyWithDifferentPayload() {
        AgentExchangeRequest existing = completedRequest(
                "key-003",
                10L,
                6L,
                true,
                "EXCHANGE_PROCESSING",
                "已受理"
        );
        when(requestMapper.selectByIdempotencyKey("key-003")).thenReturn(existing);

        AgentToolResponse<Void> response = service.exchange(10L, 5L, "key-003");

        assertFalse(response.success());
        assertEquals("IDEMPOTENCY_KEY_CONFLICT", response.code());
        verify(userAwardService, never()).exchange(any(), any());
    }

    @Test
    void shouldReturnInProgressWhenConcurrentInsertLosesUniqueKeyRace() {
        AgentExchangeRequest executing = request(
                "key-004",
                10L,
                6L,
                "EXECUTING"
        );
        when(requestMapper.selectByIdempotencyKey("key-004"))
                .thenReturn(null, executing);
        when(requestMapper.insert(any(AgentExchangeRequest.class)))
                .thenThrow(new DuplicateKeyException("duplicate"));

        AgentToolResponse<Void> response = service.exchange(10L, 6L, "key-004");

        assertFalse(response.success());
        assertTrue(response.retryable());
        assertEquals("IDEMPOTENCY_REQUEST_IN_PROGRESS", response.code());
        verify(userAwardService, never()).exchange(any(), any());
    }

    @Test
    void shouldPersistUnknownAndNeverReplayAfterSubmissionException() {
        when(requestMapper.selectByIdempotencyKey("key-005")).thenReturn(null);
        when(requestMapper.insert(any(AgentExchangeRequest.class))).thenReturn(1);
        when(userAwardService.exchange(10L, 6L))
                .thenThrow(new IllegalStateException("mq result unavailable"));
        when(requestMapper.markUnknown(any(), any())).thenReturn(1);

        AgentToolResponse<Void> response = service.exchange(10L, 6L, "key-005");

        assertFalse(response.success());
        assertFalse(response.retryable());
        assertEquals("SUBMISSION_UNKNOWN", response.code());
        verify(requestMapper).markUnknown(
                "key-005",
                "当前无法判断兑换请求是否已受理，请先到订单页面核对，不要立即重复兑换"
        );
    }

    @Test
    void shouldTurnStaleExecutingRequestIntoUnknownWithoutReplay() {
        AgentExchangeRequest executing = request(
                "key-006",
                10L,
                6L,
                "EXECUTING"
        );
        executing.setUpdateTime(new Date(System.currentTimeMillis() - 31_000L));
        when(requestMapper.selectByIdempotencyKey("key-006")).thenReturn(executing);
        when(requestMapper.markUnknown(any(), any())).thenReturn(1);

        AgentToolResponse<Void> response = service.exchange(10L, 6L, "key-006");

        assertFalse(response.success());
        assertEquals("SUBMISSION_UNKNOWN", response.code());
        verify(requestMapper).markUnknown(
                "key-006",
                "当前无法判断兑换请求是否已受理，请先到订单页面核对，不要立即重复兑换"
        );
        verify(userAwardService, never()).exchange(any(), any());
    }

    private AgentExchangeRequest completedRequest(
            String key,
            Long userId,
            Long awardId,
            boolean success,
            String code,
            String message
    ) {
        AgentExchangeRequest request = request(key, userId, awardId, "COMPLETED");
        request.setResponseSuccess(success);
        request.setResponseCode(code);
        request.setResponseMessage(message);
        request.setResponseRetryable(false);
        return request;
    }

    private AgentExchangeRequest request(String key, Long userId, Long awardId, String status) {
        AgentExchangeRequest request = new AgentExchangeRequest();
        request.setIdempotencyKey(key);
        request.setRequestFingerprint(fingerprint(userId, awardId));
        request.setUserId(userId);
        request.setAwardId(awardId);
        request.setStatus(status);
        request.setCreateTime(new Date());
        request.setUpdateTime(new Date());
        return request;
    }

    private String fingerprint(Long userId, Long awardId) {
        try {
            byte[] digest = java.security.MessageDigest.getInstance("SHA-256")
                    .digest(("userId=" + userId + "&awardId=" + awardId)
                            .getBytes(java.nio.charset.StandardCharsets.UTF_8));
            return java.util.HexFormat.of().formatHex(digest);
        } catch (java.security.NoSuchAlgorithmException exception) {
            throw new IllegalStateException(exception);
        }
    }
}
