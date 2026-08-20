package com.budou.incentive.controller;

import com.budou.incentive.dto.agent.AgentToolResponse;
import com.budou.incentive.service.UserAwardService;
import com.budou.incentive.utils.Result;
import com.budou.incentive.utils.ResultCodeEnum;
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
    private UserAwardService userAwardService;

    private AgentCommandController controller;

    @BeforeEach
    void setUp() {
        controller = new AgentCommandController(userAwardService);
    }

    @Test
    void shouldMapAcceptedOldChainResultToProcessing() {
        when(userAwardService.exchange(10L, 6L))
                .thenReturn(Result.build(null, ResultCodeEnum.Query_Later));

        AgentToolResponse<Void> response = controller.exchange(
                10L, 6L, "request-001", "confirmation-001"
        );

        assertTrue(response.success());
        assertEquals("EXCHANGE_PROCESSING", response.code());
        verify(userAwardService).exchange(10L, 6L);
    }

    @Test
    void shouldPreserveAlreadyRedeemedMeaning() {
        when(userAwardService.exchange(10L, 6L))
                .thenReturn(Result.build(null, ResultCodeEnum.AWARD_REDEEMED));

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
        verifyNoInteractions(userAwardService);
    }
}
