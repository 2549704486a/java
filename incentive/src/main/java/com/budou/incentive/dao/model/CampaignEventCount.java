package com.budou.incentive.dao.model;

import lombok.Data;

@Data
public class CampaignEventCount {
    private String experimentGroup;
    private String eventType;
    private Integer eventUsers;
}
