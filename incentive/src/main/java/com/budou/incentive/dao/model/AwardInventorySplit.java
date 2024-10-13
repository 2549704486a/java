package com.budou.incentive.dao.model;

import lombok.Data;

/**
 * @program: incentive-事务消息
 * @description:
 * @author: 阿伟
 * @create: 2024-10-05 20:12
 **/
@Data
public class AwardInventorySplit {
    private Long splitId;

    private Long awardId;

    private Integer inventory;
}
