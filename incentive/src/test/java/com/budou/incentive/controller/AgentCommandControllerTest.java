package com.budou.incentive.controller;

import com.budou.incentive.dto.agent.AgentToolResponse;
import com.budou.incentive.service.AgentExchangeCommandService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class AgentCommandControllerTest {

    @Mock
    private AgentExchangeCommandService commandService;

    private AgentCommandController controller;

    @BeforeEach
    void setUp() {
        controller = new AgentCommandController(commandService);
    }

    @Test
    void shouldMapAcceptedOldChainResultToProcessing() {
        when(commandService.exchange(10L, 6L, "confirmation-001"))
                .thenReturn(AgentToolResponse.ok(
                        "EXCHANGE_PROCESSING",
                        null,
                        "兑换请求已进入处理流程，请到订单页面查看最终结果"
                ));

        AgentToolResponse<Void> response = controller.exchange(
                10L, 6L, "request-001", "confirmation-001"
        );

        assertTrue(response.success());
        assertEquals("EXCHANGE_PROCESSING", response.code());
        verify(commandService).exchange(10L, 6L, "confirmation-001");
    }

    @Test
    void shouldPreserveAlreadyRedeemedMeaning() {
        when(commandService.exchange(10L, 6L, "confirmation-002"))
                .thenReturn(AgentToolResponse.fail(
                        "ALREADY_REDEEMED",
                        "该奖品已经兑换或已有兑换记录",
                        false
                ));

        AgentToolResponse<Void> response = controller.exchange(
                10L, 6L, "request-002", "confirmation-002"
        );

        assertFalse(response.success());
        assertEquals("ALREADY_REDEEMED", response.code());
    }

    @Test
    void shouldRejectInvalidConfirmationWithoutCallingOldChain() {
        AgentToolResponse<Void> response = controller.exchange(
                10L, 6L, "request-003", " "
        );

        assertFalse(response.success());
        assertEquals("INVALID_IDEMPOTENCY_KEY", response.code());
        verifyNoInteractions(commandService);
    }

    @Test
    void shouldRejectNonAsciiIdempotencyKey() {
        AgentToolResponse<Void> response = controller.exchange(
                10L, 6L, "request-004", "确认-001"
        );

        assertFalse(response.success());
        assertEquals("INVALID_IDEMPOTENCY_KEY", response.code());
        verifyNoInteractions(commandService);
    }
}
