package com.budou.incentive.dao.model;

import lombok.Data;

import java.util.Date;

/**
 * A business fact that can be projected into the campaign event stream.
 */
@Data
public class CampaignEventCandidate {
    private Long activityId;
    private Long userId;
    private Long referenceId;
    private Date occurredAt;
    private String source;
}
