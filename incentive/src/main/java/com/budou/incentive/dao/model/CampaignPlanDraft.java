package com.budou.incentive.dao.model;

import lombok.Data;

import java.util.Date;

@Data
public class CampaignPlanDraft {
    private Long id;
    private String draftKey;
    private Integer version;
    private String operatorId;
    private String objective;
    private String targetSegmentKey;
    private String targetSegment;
    private Long budgetAmountCents;
    private Long pointsIssuanceCap;
    private Date startAt;
    private Date endAt;
    private String planJson;
    private String status;
    private String reviewerId;
    private String reviewComment;
    private Date reviewedAt;
    private String publishedBy;
    private Date publishedAt;
    private Date createdAt;
    private Date updatedAt;
}
