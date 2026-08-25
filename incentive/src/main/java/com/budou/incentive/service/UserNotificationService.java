package com.budou.incentive.service;

import com.budou.incentive.dao.mapper.UserNotificationMapper;
import com.budou.incentive.dao.model.UserNotification;
import com.budou.incentive.dto.agent.AgentToolResponse;
import com.budou.incentive.dto.agent.UserNotificationView;
import org.springframework.stereotype.Service;

import java.util.Date;
import java.util.List;

@Service
public class UserNotificationService {

    private final UserNotificationMapper notificationMapper;

    public UserNotificationService(UserNotificationMapper notificationMapper) {
        this.notificationMapper = notificationMapper;
    }

    public AgentToolResponse<List<UserNotificationView>> list(Long userId, int limit) {
        if (userId == null || userId <= 0) {
            return AgentToolResponse.fail("INVALID_ARGUMENT", "userId 必须为正整数", false);
        }
        int safeLimit = Math.max(1, Math.min(limit, 100));
        List<UserNotificationView> notifications = notificationMapper
                .selectByUserId(userId, safeLimit)
                .stream()
                .map(this::toView)
                .toList();
        return AgentToolResponse.ok(
                notifications.isEmpty() ? "NOTIFICATIONS_EMPTY" : "NOTIFICATIONS_FOUND",
                notifications,
                notifications.isEmpty() ? "当前没有站内消息" : "站内消息读取成功"
        );
    }

    public AgentToolResponse<UserNotificationView> markRead(Long userId, Long notificationId) {
        return changeStatus(userId, notificationId, false);
    }

    public AgentToolResponse<UserNotificationView> markClicked(Long userId, Long notificationId) {
        return changeStatus(userId, notificationId, true);
    }

    private AgentToolResponse<UserNotificationView> changeStatus(
            Long userId,
            Long notificationId,
            boolean clicked) {
        if (userId == null || userId <= 0 || notificationId == null || notificationId <= 0) {
            return AgentToolResponse.fail("INVALID_ARGUMENT", "用户和消息标识必须为正整数", false);
        }
        UserNotification current = notificationMapper.selectOwned(notificationId, userId);
        if (current == null) {
            return AgentToolResponse.fail("NOTIFICATION_NOT_FOUND", "站内消息不存在", false);
        }
        Date now = new Date();
        if (clicked) {
            notificationMapper.markClicked(notificationId, userId, now);
        } else {
            notificationMapper.markRead(notificationId, userId, now);
        }
        UserNotification updated = notificationMapper.selectOwned(notificationId, userId);
        return AgentToolResponse.ok(
                clicked ? "NOTIFICATION_CLICKED" : "NOTIFICATION_READ",
                toView(updated == null ? current : updated),
                clicked ? "站内消息点击状态已记录" : "站内消息已读"
        );
    }

    private UserNotificationView toView(UserNotification notification) {
        return new UserNotificationView(
                notification.getId(),
                notification.getActivityId(),
                notification.getTitle(),
                notification.getContent(),
                notification.getStatus(),
                notification.getReadAt(),
                notification.getClickedAt(),
                notification.getCreatedAt()
        );
    }
}
