package com.budou.incentive.service;

import com.budou.incentive.dao.mapper.CampaignActivityMapper;
import com.budou.incentive.dao.mapper.CampaignDeliveryTaskMapper;
import com.budou.incentive.dao.mapper.CampaignExecutionMapper;
import com.budou.incentive.dao.mapper.CampaignTargetUserMapper;
import com.budou.incentive.dao.model.CampaignActivity;
import com.budou.incentive.dao.model.CampaignAudienceUser;
import com.budou.incentive.dao.model.CampaignDeliveryTask;
import com.budou.incentive.dao.model.CampaignExecution;
import com.budou.incentive.dao.model.CampaignTargetUser;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.ArrayList;
import java.util.Date;
import java.util.List;
import java.util.concurrent.atomic.AtomicReference;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertSame;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyList;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class CampaignExecutionServiceTest {

    private static final Date NOW = Date.from(Instant.parse("2026-08-25T08:00:00Z"));

    @Mock
    private CampaignActivityMapper activityMapper;
    @Mock
    private CampaignExecutionMapper executionMapper;
    @Mock
    private CampaignTargetUserMapper targetUserMapper;
    @Mock
    private CampaignDeliveryTaskMapper deliveryTaskMapper;
    @Mock
    private CampaignAudienceService audienceService;

    private CampaignExecutionService service;

    @BeforeEach
    void setUp() {
        service = new CampaignExecutionService(
                activityMapper,
                executionMapper,
                targetUserMapper,
                deliveryTaskMapper,
                audienceService,
                7500,
                () -> NOW
        );
    }

    @Test
    void shouldPersistFixedExperimentGroupsAndOnlyCreateTreatmentTasks() {
        CampaignActivity activity = activeActivity();
        when(executionMapper.selectByActivityId(21L)).thenReturn(null);
        when(activityMapper.selectById(21L)).thenReturn(activity);
        when(audienceService.isSupported(CampaignAudienceService.ALL_USERS)).thenReturn(true);
        when(audienceService.listUsers(CampaignAudienceService.ALL_USERS, NOW))
                .thenReturn(audienceUsers());
        when(executionMapper.insertIfAbsent(any())).thenAnswer(invocation -> {
            invocation.<CampaignExecution>getArgument(0).setId(31L);
            return 1;
        });

        AtomicReference<List<CampaignTargetUser>> persisted = new AtomicReference<>();
        when(targetUserMapper.insertBatch(anyList())).thenAnswer(invocation -> {
            List<CampaignTargetUser> targets = invocation.getArgument(0);
            long id = 100L;
            for (CampaignTargetUser target : targets) {
                target.setId(id++);
            }
            persisted.set(new ArrayList<>(targets));
            return targets.size();
        });
        when(targetUserMapper.selectByExecutionId(31L))
                .thenAnswer(invocation -> persisted.get());
        when(executionMapper.selectById(31L)).thenReturn(null);

        CampaignExecution execution = service.startActivity(21L);

        assertEquals(CampaignExecutionService.RUNNING, execution.getStatus());
        assertEquals(4, execution.getTotalUsers());
        assertEquals(3, execution.getTreatmentUsers());
        assertEquals(1, execution.getControlUsers());

        ArgumentCaptor<List<CampaignDeliveryTask>> taskCaptor = ArgumentCaptor.forClass(List.class);
        verify(deliveryTaskMapper).insertBatch(taskCaptor.capture());
        assertEquals(3, taskCaptor.getValue().size());
        assertEquals(2, taskCaptor.getValue().stream()
                .filter(task -> CampaignExecutionService.IN_APP.equals(task.getChannel()))
                .count());
        assertEquals(1, taskCaptor.getValue().stream()
                .filter(task -> CampaignExecutionService.DEMO_PUSH.equals(task.getChannel()))
                .count());
        verify(executionMapper).markRunning(31L, 4, 3, 1, NOW, NOW);
    }

    @Test
    void shouldReturnExistingExecutionWithoutRebuildingTargets() {
        CampaignExecution existing = new CampaignExecution();
        existing.setId(31L);
        existing.setActivityId(21L);
        existing.setStatus(CampaignExecutionService.RUNNING);
        when(executionMapper.selectByActivityId(21L)).thenReturn(existing);

        CampaignExecution result = service.startActivity(21L);

        assertSame(existing, result);
        verify(activityMapper, never()).selectById(any());
        verify(targetUserMapper, never()).insertBatch(anyList());
        verify(deliveryTaskMapper, never()).insertBatch(anyList());
    }

    private CampaignActivity activeActivity() {
        CampaignActivity activity = new CampaignActivity();
        activity.setId(21L);
        activity.setTargetSegmentKey(CampaignAudienceService.ALL_USERS);
        activity.setStatus("ACTIVE");
        activity.setStartAt(Date.from(NOW.toInstant().minus(1, ChronoUnit.DAYS)));
        activity.setEndAt(Date.from(NOW.toInstant().plus(1, ChronoUnit.DAYS)));
        return activity;
    }

    private List<CampaignAudienceUser> audienceUsers() {
        return List.of(
                user(1L, 900L, 1),
                user(2L, 800L, 2),
                user(3L, 700L, 3),
                user(4L, 600L, 45)
        );
    }

    private CampaignAudienceUser user(Long id, Long points, int inactiveDays) {
        CampaignAudienceUser user = new CampaignAudienceUser();
        user.setUserId(id);
        user.setPoints(points);
        user.setLastActiveAt(Date.from(NOW.toInstant().minus(inactiveDays, ChronoUnit.DAYS)));
        user.setDataSource("FIXTURE");
        return user;
    }
}
