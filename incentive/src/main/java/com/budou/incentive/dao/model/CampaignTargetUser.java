package com.budou.incentive.dao.model;

import lombok.Data;

import java.util.Date;

@Data
public class CampaignTargetUser {
    private Long id;
    private Long executionId;
    private Long activityId;
    private Long userId;
    private String experimentGroup;
    private String deliveryChannel;
    private Long pointsSnapshot;
    private Date lastActiveAtSnapshot;
    private String dataSource;
    private Date assignedAt;
}
