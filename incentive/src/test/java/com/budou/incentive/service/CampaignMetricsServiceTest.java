package com.budou.incentive.service;

import com.budou.incentive.dao.mapper.CampaignEffectMetricMapper;
import com.budou.incentive.dao.mapper.CampaignEventMapper;
import com.budou.incentive.dao.mapper.CampaignExecutionMapper;
import com.budou.incentive.dao.mapper.CampaignTargetUserMapper;
import com.budou.incentive.dao.model.CampaignEffectMetric;
import com.budou.incentive.dao.model.CampaignEventCount;
import com.budou.incentive.dao.model.CampaignExecution;
import com.budou.incentive.dto.agent.CampaignFunnelView;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.math.BigDecimal;
import java.time.Instant;
import java.util.Date;
import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class CampaignMetricsServiceTest {

    private static final Date NOW = Date.from(Instant.parse("2026-08-25T08:00:00Z"));

    @Mock
    private CampaignExecutionMapper executionMapper;
    @Mock
    private CampaignTargetUserMapper targetUserMapper;
    @Mock
    private CampaignEventMapper eventMapper;
    @Mock
    private CampaignEffectMetricMapper effectMetricMapper;

    private CampaignMetricsService service;

    @BeforeEach
    void setUp() {
        service = new CampaignMetricsService(
                executionMapper,
                targetUserMapper,
                eventMapper,
                effectMetricMapper,
                () -> NOW
        );
    }

    @Test
    void shouldCalculateTreatmentControlFunnelAndLift() {
        when(executionMapper.selectByActivityId(7L)).thenReturn(execution());
        when(targetUserMapper.countNonRealByActivityId(7L)).thenReturn(20);
        when(eventMapper.countDistinctUsersByGroupAndType(7L)).thenReturn(List.of(
                count("TREATMENT", "DELIVERED", 8),
                count("TREATMENT", "VIEW", 6),
                count("TREATMENT", "CLICK", 4),
                count("TREATMENT", "TASK_COMPLETE", 5),
                count("TREATMENT", "EXCHANGE", 3),
                count("CONTROL", "TASK_COMPLETE", 2),
                count("CONTROL", "EXCHANGE", 1)
        ));
        when(effectMetricMapper.upsert(any())).thenReturn(1);

        CampaignFunnelView result = service.refreshAndGet(7L);

        assertEquals("SIMULATED", result.dataSource());
        assertEquals(new BigDecimal("0.800000"), result.treatment().deliveryRate());
        assertEquals(new BigDecimal("0.750000"), result.treatment().viewRate());
        assertEquals(new BigDecimal("0.500000"), result.treatment().clickRate());
        assertEquals(new BigDecimal("0.500000"), result.treatment().taskCompletionRate());
        assertEquals(new BigDecimal("0.300000"), result.treatment().exchangeRate());
        assertEquals(new BigDecimal("0.200000"), result.control().taskCompletionRate());
        assertEquals(new BigDecimal("0.100000"), result.control().exchangeRate());
        assertEquals(new BigDecimal("0.300000"), result.taskCompletionLift());
        assertEquals(new BigDecimal("0.200000"), result.exchangeLift());

        ArgumentCaptor<CampaignEffectMetric> captor =
                ArgumentCaptor.forClass(CampaignEffectMetric.class);
        verify(effectMetricMapper, times(9)).upsert(captor.capture());
        assertEquals("AUTO_EXECUTION:9", captor.getAllValues().get(0).getSourceRef());
    }

    @Test
    void shouldKeepFunnelQueryReadOnly() {
        when(executionMapper.selectByActivityId(7L)).thenReturn(execution());
        when(targetUserMapper.countNonRealByActivityId(7L)).thenReturn(20);
        when(eventMapper.countDistinctUsersByGroupAndType(7L)).thenReturn(List.of());

        service.getFunnel(7L);

        verify(effectMetricMapper, never()).upsert(any());
    }

    private CampaignExecution execution() {
        CampaignExecution execution = new CampaignExecution();
        execution.setId(9L);
        execution.setActivityId(7L);
        execution.setTotalUsers(20);
        execution.setTreatmentUsers(10);
        execution.setControlUsers(10);
        return execution;
    }

    private CampaignEventCount count(String group, String type, int users) {
        CampaignEventCount count = new CampaignEventCount();
        count.setExperimentGroup(group);
        count.setEventType(type);
        count.setEventUsers(users);
        return count;
    }
}
