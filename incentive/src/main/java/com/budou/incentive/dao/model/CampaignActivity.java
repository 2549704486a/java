package com.budou.incentive.dao.model;

import lombok.Data;

import java.util.Date;

@Data
public class CampaignActivity {
    private Long id;
    private Long draftId;
    private String objective;
    private String targetSegmentKey;
    private Long budgetAmountCents;
    private Long pointsIssuanceCap;
    private Date startAt;
    private Date endAt;
    private String planJson;
    private String status;
    private String publishedBy;
    private Date publishedAt;
    private Date createdAt;
    private Date updatedAt;
}
