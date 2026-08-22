package com.budou.incentive.dao.model;

import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.math.BigDecimal;
import java.util.Date;

@Data
@NoArgsConstructor
@AllArgsConstructor
public class CampaignMetricHistory {
    private Long id;
    private String segmentKey;
    private String metricName;
    private BigDecimal metricValue;
    private Integer sampleSize;
    private Date measuredAt;
    private String sourceRef;
}
