package com.budou.incentive.dao.model;

import jakarta.persistence.criteria.CriteriaBuilder;
import lombok.Data;

/**
 * @program: incentive-事务消息
 * @description:
 * @author: 阿伟
 * @create: 2024-09-28 09:23
 **/
@Data
public class UserCurrency {

    private Long id;

    private Long userId;

    private Integer currency;

}
