package com.budou.incentive.service;

import com.budou.incentive.dao.mapper.CampaignActivityMapper;
import com.budou.incentive.dao.mapper.CampaignDeliveryTaskMapper;
import com.budou.incentive.dao.mapper.CampaignExecutionMapper;
import com.budou.incentive.dao.mapper.UserNotificationMapper;
import com.budou.incentive.dao.model.CampaignActivity;
import com.budou.incentive.dao.model.CampaignDeliveryTask;
import com.budou.incentive.dao.model.UserNotification;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.Date;

@Slf4j
@Service
public class CampaignDeliveryService {

    private final CampaignDeliveryTaskMapper deliveryTaskMapper;
    private final CampaignExecutionMapper executionMapper;
    private final CampaignActivityMapper activityMapper;
    private final UserNotificationMapper notificationMapper;

    public CampaignDeliveryService(
            CampaignDeliveryTaskMapper deliveryTaskMapper,
            CampaignExecutionMapper executionMapper,
            CampaignActivityMapper activityMapper,
            UserNotificationMapper notificationMapper) {
        this.deliveryTaskMapper = deliveryTaskMapper;
        this.executionMapper = executionMapper;
        this.activityMapper = activityMapper;
        this.notificationMapper = notificationMapper;
    }

    @Transactional
    public void consumeInAppTask(Long deliveryTaskId) {
        CampaignDeliveryTask task = deliveryTaskMapper.selectById(deliveryTaskId);
        if (task == null || "SENT".equals(task.getStatus()) || "DEAD".equals(task.getStatus())) {
            return;
        }
        if (!CampaignExecutionService.IN_APP.equals(task.getChannel())) {
            throw new IllegalArgumentException("站内信消费者收到非 IN_APP 任务");
        }

        CampaignActivity activity = activityMapper.selectById(task.getActivityId());
        if (activity == null) {
            throw new IllegalStateException("投放任务关联的活动不存在");
        }

        Date now = new Date();
        UserNotification notification = new UserNotification();
        notification.setDeliveryTaskId(task.getId());
        notification.setActivityId(task.getActivityId());
        notification.setUserId(task.getUserId());
        notification.setTitle("积分活动提醒");
        notification.setContent(activity.getObjective());
        notification.setStatus("UNREAD");
        notification.setCreatedAt(now);
        notification.setUpdatedAt(now);
        notificationMapper.insertIfAbsent(notification);

        // 只有首次把任务推进到 SENT 才累加执行计数；重复消息只读取已有事实后返回。
        if (deliveryTaskMapper.markSent(task.getId(), now) == 1) {
            executionMapper.incrementSentUsers(task.getExecutionId(), now);
            log.info("campaign delivery consumed, taskId={}, activityId={}, userId={}",
                    task.getId(), task.getActivityId(), task.getUserId());
        }
    }
}
