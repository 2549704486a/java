package com.budou.incentive.dto.agent;

import java.math.BigDecimal;
import java.util.Date;

public record CampaignEffectMetricView(
        Long id,
        Long activityId,
        String metricName,
        BigDecimal metricValue,
        Integer sampleSize,
        Date measuredAt,
        String sourceRef,
        String recordedBy,
        Date createdAt
) {
}
