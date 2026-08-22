package com.budou.incentive.dao.model;

import lombok.AllArgsConstructor;
import lombok.Data;

import java.util.Date;

/**
 * @program: incentive-事务消息
 * @description:
 * @author: 阿伟
 * @create: 2024-09-28 09:33
 **/
@AllArgsConstructor
@Data
public class AwardConfig {

    private Long awardId;

    private String coverUrl;

    private String name;

    private Integer awardType;

    private Integer inventory;

    private Integer price;

    /** 奖品单位成本（分），不能由兑换积分推算。 */
    private Integer unitCostCents;

    private Date startTime;

    private Date endTime;

    private Date createTime;

    private Date updateTime;

    private Integer initInventory;

    private Integer isOverSell;

    public AwardConfig() {

    }
}
