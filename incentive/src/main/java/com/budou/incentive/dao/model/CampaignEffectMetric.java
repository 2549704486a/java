package com.budou.incentive.dao.model;

import lombok.Data;

import java.math.BigDecimal;
import java.util.Date;

@Data
public class CampaignEffectMetric {
    private Long id;
    private Long activityId;
    private String metricName;
    private BigDecimal metricValue;
    private Integer sampleSize;
    private Date measuredAt;
    private String sourceRef;
    private String recordedBy;
    private Date createdAt;
}
