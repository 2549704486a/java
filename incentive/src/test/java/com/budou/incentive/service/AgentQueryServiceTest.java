package com.budou.incentive.service;

import com.budou.incentive.dao.mapper.AwardConfigMapper;
import com.budou.incentive.dao.mapper.FinishTaskRecordMapper;
import com.budou.incentive.dao.mapper.TaskConfigMapper;
import com.budou.incentive.dao.mapper.UserAwardMapper;
import com.budou.incentive.dao.mapper.UserCurrencyMapper;
import com.budou.incentive.dao.model.AwardConfig;
import com.budou.incentive.dao.model.FinishTaskRecord;
import com.budou.incentive.dao.model.TaskConfig;
import com.budou.incentive.dto.agent.AgentToolResponse;
import com.budou.incentive.dto.agent.ExchangeEligibilityView;
import com.budou.incentive.dto.agent.TaskOptionView;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.util.Date;
import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class AgentQueryServiceTest {

    @Mock
    private UserCurrencyMapper userCurrencyMapper;
    @Mock
    private TaskConfigMapper taskConfigMapper;
    @Mock
    private FinishTaskRecordMapper finishTaskRecordMapper;
    @Mock
    private AwardConfigMapper awardConfigMapper;
    @Mock
    private UserAwardMapper userAwardMapper;

    private AgentQueryService service;

    @BeforeEach
    void setUp() {
        service = new AgentQueryService(
                userCurrencyMapper,
                taskConfigMapper,
                finishTaskRecordMapper,
                awardConfigMapper,
                userAwardMapper
        );
    }

    @Test
    void shouldReturnUserNotFoundWhenPointsDoNotExist() {
        when(userCurrencyMapper.selectCurrency(10L)).thenReturn(null);

        AgentToolResponse<?> response = service.getUserPoints(10L);

        assertFalse(response.success());
        assertEquals("USER_NOT_FOUND", response.code());
    }

    @Test
    void shouldKeepAvailableAndUnclaimedTasksButExcludeRewardedTasks() {
        when(userCurrencyMapper.selectCurrency(10L)).thenReturn(80);
        when(taskConfigMapper.selectActiveTasks(any(Date.class))).thenReturn(List.of(
                task(1L, "签到", 10),
                task(2L, "分享", 30),
                task(3L, "浏览", 20)
        ));
        when(finishTaskRecordMapper.selectUserTaskRecords(10L)).thenReturn(List.of(
                new FinishTaskRecord(1L, 10L, 2L, 0, new Date()),
                new FinishTaskRecord(2L, 10L, 3L, 1, new Date())
        ));

        AgentToolResponse<List<TaskOptionView>> response = service.listAvailableTasks(10L);

        assertTrue(response.success());
        assertEquals(2, response.data().size());
        assertEquals("AVAILABLE", response.data().get(0).status());
        assertEquals("COMPLETED_UNCLAIMED", response.data().get(1).status());
    }

    @Test
    void shouldCalculatePointsGapWhenPointsAreInsufficient() {
        when(userCurrencyMapper.selectCurrency(10L)).thenReturn(80);
        when(awardConfigMapper.selectAwardInfo(6L)).thenReturn(activeAward(6L, 200));
        when(userAwardMapper.selectStatus(10L, 6L)).thenReturn(null);

        AgentToolResponse<ExchangeEligibilityView> response = service.checkExchangeEligibility(10L, 6L);

        assertTrue(response.success());
        assertFalse(response.data().eligible());
        assertEquals("INSUFFICIENT_POINTS", response.code());
        assertEquals(120, response.data().pointsGap());
    }

    @Test
    void shouldReportAlreadyRedeemedBeforeSuggestingTasks() {
        when(userCurrencyMapper.selectCurrency(10L)).thenReturn(1000);
        when(awardConfigMapper.selectAwardInfo(6L)).thenReturn(activeAward(6L, 200));
        when(userAwardMapper.selectStatus(10L, 6L)).thenReturn(1);

        AgentToolResponse<ExchangeEligibilityView> response = service.checkExchangeEligibility(10L, 6L);

        assertTrue(response.success());
        assertFalse(response.data().eligible());
        assertEquals("ALREADY_REDEEMED", response.code());
    }

    @Test
    void shouldReportAwardNotStarted() {
        when(userCurrencyMapper.selectCurrency(10L)).thenReturn(1000);
        AwardConfig award = activeAward(6L, 200);
        award.setStartTime(new Date(System.currentTimeMillis() + 60_000));
        when(awardConfigMapper.selectAwardInfo(6L)).thenReturn(award);
        when(userAwardMapper.selectStatus(10L, 6L)).thenReturn(null);

        AgentToolResponse<ExchangeEligibilityView> response = service.checkExchangeEligibility(10L, 6L);

        assertTrue(response.success());
        assertFalse(response.data().eligible());
        assertEquals("AWARD_NOT_STARTED", response.code());
    }

    private TaskConfig task(Long taskId, String name, Integer rewardPoints) {
        Date now = new Date();
        return new TaskConfig(taskId, name, rewardPoints,
                new Date(now.getTime() - 60_000), new Date(now.getTime() + 60_000), 1, name + "任务");
    }

    private AwardConfig activeAward(Long awardId, Integer requiredPoints) {
        Date now = new Date();
        return new AwardConfig(
                awardId, "/cover.png", "测试奖品", 1, 100, requiredPoints,
                new Date(now.getTime() - 60_000), new Date(now.getTime() + 60_000),
                now, now, 100, 0
        );
    }
}
