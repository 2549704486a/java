package com.budou.incentive.dao.model;

import lombok.Data;

import java.util.Date;

@Data
public class CampaignDeliveryTask {
    private Long id;
    private Long executionId;
    private Long activityId;
    private Long targetUserId;
    private Long userId;
    private String channel;
    private String status;
    private Integer attemptCount;
    private Integer maxAttempts;
    private Date nextAttemptAt;
    private Date claimedAt;
    private Date sentAt;
    private String lastError;
    private Date createdAt;
    private Date updatedAt;
}
