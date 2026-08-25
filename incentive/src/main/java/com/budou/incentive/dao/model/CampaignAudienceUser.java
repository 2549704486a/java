package com.budou.incentive.dao.model;

import lombok.Data;

import java.util.Date;

/**
 * 活动圈选查询返回的用户事实快照，不对应独立数据表。
 */
@Data
public class CampaignAudienceUser {
    private Long userId;
    private Long points;
    private Date lastActiveAt;
    private String dataSource;
}
