package com.budou.incentive.dto.agent;

import java.util.Date;

public record CampaignDraftView(
        Long id,
        String draftKey,
        Integer version,
        String operatorId,
        String objective,
        String targetSegmentKey,
        String targetSegment,
        Long budgetAmountCents,
        Long pointsIssuanceCap,
        Date startAt,
        Date endAt,
        String planJson,
        String status,
        String reviewerId,
        String reviewComment,
        Date reviewedAt,
        String publishedBy,
        Date publishedAt,
        Date createdAt,
        Date updatedAt
) {
}
