package com.budou.incentive.dto.agent;

import java.math.BigDecimal;
import java.util.Date;

public record HistoricalCampaignMetricView(
        String metricName,
        BigDecimal value,
        Integer sampleSize,
        Date asOf,
        String sourceRef
) {
}
