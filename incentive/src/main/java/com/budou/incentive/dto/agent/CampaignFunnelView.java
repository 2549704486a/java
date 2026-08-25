package com.budou.incentive.dto.agent;

import java.math.BigDecimal;
import java.util.Date;

public record CampaignFunnelView(
        Long activityId,
        Long executionId,
        String dataSource,
        CampaignGroupFunnelView treatment,
        CampaignGroupFunnelView control,
        BigDecimal taskCompletionLift,
        BigDecimal exchangeLift,
        Date measuredAt
) {
}
