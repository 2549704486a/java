package com.budou.incentive.dao.model;

import lombok.Data;

import java.util.Date;

@Data
public class CampaignEvent {
    private Long id;
    private String eventKey;
    private Long activityId;
    private Long userId;
    private String eventType;
    private String source;
    private Date occurredAt;
    private String metadataJson;
    private Date createdAt;
}
