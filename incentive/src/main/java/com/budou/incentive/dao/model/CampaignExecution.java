package com.budou.incentive.dao.model;

import lombok.Data;

import java.util.Date;

@Data
public class CampaignExecution {
    private Long id;
    private Long activityId;
    private String status;
    private Integer treatmentRatioBps;
    private Integer totalUsers;
    private Integer treatmentUsers;
    private Integer controlUsers;
    private Integer sentUsers;
    private Integer failedUsers;
    private Integer version;
    private Date startedAt;
    private Date completedAt;
    private String lastError;
    private Date createdAt;
    private Date updatedAt;
}
