package com.budou.incentive.dto.agent;

import java.util.Date;

public record CampaignDraftCreateCommand(
        String draftKey,
        String operatorId,
        String objective,
        String targetSegmentKey,
        String targetSegment,
        Long budgetAmountCents,
        Long pointsIssuanceCap,
        Date startAt,
        Date endAt,
        String planJson
) {
}
