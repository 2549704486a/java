package com.budou.incentive.service;

import com.budou.incentive.dao.mapper.UserNotificationMapper;
import com.budou.incentive.dao.model.UserNotification;
import com.budou.incentive.dto.agent.AgentToolResponse;
import com.budou.incentive.dto.agent.UserNotificationView;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class UserNotificationServiceTest {

    @Mock
    private UserNotificationMapper notificationMapper;

    @Test
    void shouldListOnlyCurrentUsersNotifications() {
        when(notificationMapper.selectByUserId(10L, 50)).thenReturn(List.of(notification("UNREAD")));

        AgentToolResponse<List<UserNotificationView>> response = service().list(10L, 50);

        assertTrue(response.success());
        assertEquals("NOTIFICATIONS_FOUND", response.code());
        assertEquals(1, response.data().size());
        assertEquals(10L, notificationMapper.selectByUserId(10L, 50).get(0).getUserId());
    }

    @Test
    void shouldRejectChangingAnotherUsersNotification() {
        when(notificationMapper.selectOwned(81L, 10L)).thenReturn(null);

        AgentToolResponse<UserNotificationView> response = service().markRead(10L, 81L);

        assertFalse(response.success());
        assertEquals("NOTIFICATION_NOT_FOUND", response.code());
        verify(notificationMapper, never()).markRead(any(), any(), any());
    }

    private UserNotificationService service() {
        return new UserNotificationService(notificationMapper);
    }

    private UserNotification notification(String status) {
        UserNotification notification = new UserNotification();
        notification.setId(81L);
        notification.setActivityId(21L);
        notification.setUserId(10L);
        notification.setTitle("积分活动提醒");
        notification.setContent("看看新活动");
        notification.setStatus(status);
        return notification;
    }
}
