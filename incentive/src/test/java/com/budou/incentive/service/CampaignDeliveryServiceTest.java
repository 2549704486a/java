package com.budou.incentive.service;

import com.budou.incentive.dao.mapper.CampaignActivityMapper;
import com.budou.incentive.dao.mapper.CampaignDeliveryTaskMapper;
import com.budou.incentive.dao.mapper.CampaignExecutionMapper;
import com.budou.incentive.dao.mapper.UserNotificationMapper;
import com.budou.incentive.dao.model.CampaignActivity;
import com.budou.incentive.dao.model.CampaignDeliveryTask;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class CampaignDeliveryServiceTest {

    @Mock
    private CampaignDeliveryTaskMapper taskMapper;
    @Mock
    private CampaignExecutionMapper executionMapper;
    @Mock
    private CampaignActivityMapper activityMapper;
    @Mock
    private UserNotificationMapper notificationMapper;

    @Test
    void shouldCreateOneNotificationAndAdvanceTask() {
        CampaignDeliveryTask task = task("PROCESSING");
        CampaignActivity activity = new CampaignActivity();
        activity.setId(21L);
        activity.setObjective("唤醒积分用户并推荐可兑换奖品");
        when(taskMapper.selectById(31L)).thenReturn(task);
        when(activityMapper.selectById(21L)).thenReturn(activity);
        when(taskMapper.markSent(any(), any())).thenReturn(1);

        service().consumeInAppTask(31L);

        verify(notificationMapper).insertIfAbsent(any());
        verify(executionMapper).incrementSentUsers(any(), any());
    }

    @Test
    void shouldIgnoreAlreadySentDuplicateMessage() {
        when(taskMapper.selectById(31L)).thenReturn(task("SENT"));

        service().consumeInAppTask(31L);

        verify(notificationMapper, never()).insertIfAbsent(any());
        verify(taskMapper, never()).markSent(any(), any());
    }

    private CampaignDeliveryService service() {
        return new CampaignDeliveryService(
                taskMapper,
                executionMapper,
                activityMapper,
                notificationMapper
        );
    }

    private CampaignDeliveryTask task(String status) {
        CampaignDeliveryTask task = new CampaignDeliveryTask();
        task.setId(31L);
        task.setExecutionId(11L);
        task.setActivityId(21L);
        task.setUserId(10L);
        task.setChannel(CampaignExecutionService.IN_APP);
        task.setStatus(status);
        return task;
    }
}
