package com.budou.incentive.dto.agent;

import java.math.BigDecimal;
import java.util.Date;

public record CampaignEffectMetricCommand(
        String operatorId,
        String metricName,
        BigDecimal metricValue,
        Integer sampleSize,
        Date measuredAt,
        String sourceRef
) {
}
