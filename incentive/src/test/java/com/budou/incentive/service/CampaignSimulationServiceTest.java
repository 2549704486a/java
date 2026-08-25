package com.budou.incentive.service;

import com.budou.incentive.dao.mapper.CampaignEventMapper;
import com.budou.incentive.dao.mapper.CampaignExecutionMapper;
import com.budou.incentive.dao.mapper.CampaignTargetUserMapper;
import com.budou.incentive.dao.model.CampaignEvent;
import com.budou.incentive.dao.model.CampaignExecution;
import com.budou.incentive.dao.model.CampaignTargetUser;
import com.budou.incentive.dto.agent.AgentToolResponse;
import com.budou.incentive.dto.agent.CampaignSimulationCommand;
import com.budou.incentive.dto.agent.CampaignSimulationView;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.time.Instant;
import java.util.Date;
import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class CampaignSimulationServiceTest {

    @Mock
    private CampaignExecutionMapper executionMapper;
    @Mock
    private CampaignTargetUserMapper targetUserMapper;
    @Mock
    private CampaignEventMapper eventMapper;
    @Mock
    private CampaignMetricsService metricsService;

    @Test
    void shouldGenerateDeterministicFixtureEvents() {
        CampaignExecution execution = execution(9L, 7L);
        when(executionMapper.selectByActivityId(7L)).thenReturn(execution);
        when(targetUserMapper.selectByExecutionId(9L)).thenReturn(List.of(
                target(7L, 10L, "TREATMENT", "FIXTURE"),
                target(7L, 11L, "TREATMENT", "FIXTURE"),
                target(7L, 12L, "TREATMENT", "FIXTURE"),
                target(7L, 13L, "TREATMENT", "FIXTURE"),
                target(7L, 14L, "CONTROL", "FIXTURE")
        ));
        when(eventMapper.insertIfAbsent(any())).thenReturn(1);
        Date now = Date.from(Instant.parse("2026-08-25T08:00:00Z"));
        CampaignSimulationService service = new CampaignSimulationService(
                executionMapper,
                targetUserMapper,
                eventMapper,
                metricsService,
                () -> now
        );

        AgentToolResponse<CampaignSimulationView> response = service.simulate(
                7L,
                new CampaignSimulationCommand(CampaignSimulationService.DEMO_BASELINE_V1)
        );

        assertTrue(response.success());
        assertEquals("CAMPAIGN_SIMULATION_APPLIED", response.code());
        assertEquals(13, response.data().insertedEvents());
        ArgumentCaptor<CampaignEvent> captor = ArgumentCaptor.forClass(CampaignEvent.class);
        verify(eventMapper, org.mockito.Mockito.times(13)).insertIfAbsent(captor.capture());
        assertEquals(4, count(captor.getAllValues(), "DELIVERED"));
        assertEquals(3, count(captor.getAllValues(), "VIEW"));
        assertEquals(2, count(captor.getAllValues(), "CLICK"));
        assertEquals(3, count(captor.getAllValues(), "TASK_COMPLETE"));
        assertEquals(1, count(captor.getAllValues(), "EXCHANGE"));
        assertTrue(captor.getAllValues().stream()
                .allMatch(event -> event.getEventKey().startsWith("simulation:DEMO_BASELINE_V1:")));
        verify(metricsService).refreshAndGet(7L);
    }

    @Test
    void shouldRejectActivityContainingRealUsers() {
        CampaignExecution execution = execution(9L, 7L);
        when(executionMapper.selectByActivityId(7L)).thenReturn(execution);
        when(targetUserMapper.selectByExecutionId(9L)).thenReturn(List.of(
                target(7L, 10L, "TREATMENT", "FIXTURE"),
                target(7L, 11L, "CONTROL", "REAL")
        ));
        CampaignSimulationService service = new CampaignSimulationService(
                executionMapper,
                targetUserMapper,
                eventMapper,
                metricsService,
                Date::new
        );

        AgentToolResponse<CampaignSimulationView> response = service.simulate(
                7L,
                new CampaignSimulationCommand(CampaignSimulationService.DEMO_BASELINE_V1)
        );

        assertEquals("CAMPAIGN_SIMULATION_REQUIRES_FIXTURE", response.code());
        verifyNoInteractions(eventMapper, metricsService);
    }

    @Test
    void shouldReturnIdempotentResultWhenEventsAlreadyExist() {
        CampaignExecution execution = execution(9L, 7L);
        when(executionMapper.selectByActivityId(7L)).thenReturn(execution);
        when(targetUserMapper.selectByExecutionId(9L)).thenReturn(List.of(
                target(7L, 10L, "TREATMENT", "FIXTURE")
        ));
        when(eventMapper.insertIfAbsent(any())).thenReturn(0);
        CampaignSimulationService service = new CampaignSimulationService(
                executionMapper,
                targetUserMapper,
                eventMapper,
                metricsService,
                Date::new
        );

        AgentToolResponse<CampaignSimulationView> response = service.simulate(
                7L,
                new CampaignSimulationCommand(CampaignSimulationService.DEMO_BASELINE_V1)
        );

        assertEquals("CAMPAIGN_SIMULATION_ALREADY_APPLIED", response.code());
        assertEquals(0, response.data().insertedEvents());
        verify(metricsService).refreshAndGet(7L);
    }

    private CampaignExecution execution(Long id, Long activityId) {
        CampaignExecution execution = new CampaignExecution();
        execution.setId(id);
        execution.setActivityId(activityId);
        return execution;
    }

    private CampaignTargetUser target(Long activityId,
                                      Long userId,
                                      String group,
                                      String dataSource) {
        CampaignTargetUser target = new CampaignTargetUser();
        target.setActivityId(activityId);
        target.setUserId(userId);
        target.setExperimentGroup(group);
        target.setDataSource(dataSource);
        return target;
    }

    private long count(List<CampaignEvent> events, String eventType) {
        return events.stream().filter(event -> eventType.equals(event.getEventType())).count();
    }
}
