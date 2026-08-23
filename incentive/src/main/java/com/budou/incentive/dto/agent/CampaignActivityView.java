package com.budou.incentive.dto.agent;

import java.util.Date;

public record CampaignActivityView(
        Long id,
        Long draftId,
        String objective,
        String targetSegmentKey,
        Long budgetAmountCents,
        Long pointsIssuanceCap,
        Date startAt,
        Date endAt,
        String planJson,
        String status,
        String publishedBy,
        Date publishedAt,
        Date createdAt,
        Date updatedAt
) {
}
