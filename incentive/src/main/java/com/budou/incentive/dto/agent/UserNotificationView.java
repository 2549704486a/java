package com.budou.incentive.dto.agent;

import java.util.Date;

public record UserNotificationView(
        Long id,
        Long activityId,
        String title,
        String content,
        String status,
        Date readAt,
        Date clickedAt,
        Date createdAt
) {
}
