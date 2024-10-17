package com.budou.incentive.dao.model;

import lombok.AllArgsConstructor;
import lombok.Data;

import java.util.Date;

/**
 * @program: incentive
 * @description:
 * @author: 阿伟
 * @create: 2024-10-15 18:39
 **/
@AllArgsConstructor
@Data
public class AddCurrencyRecord {
    private Long id;

    private Long userId;

    private Integer currency;

    private Integer afterCurrency;

    private String requestId;

    private String Description;

    private Date createTime;
}
