package com.budou.incentive.dao.model;

import lombok.Data;

import java.util.Date;

@Data
public class UserNotification {
    private Long id;
    private Long deliveryTaskId;
    private Long activityId;
    private Long userId;
    private String title;
    private String content;
    private String status;
    private Date readAt;
    private Date clickedAt;
    private Date createdAt;
    private Date updatedAt;
}
