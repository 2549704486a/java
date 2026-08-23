package com.budou.incentive.dao.model;

import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.util.Date;

@Data
@NoArgsConstructor
@AllArgsConstructor
public class UserAwardRecord {

    private Long orderId;
    private Long awardId;
    private String awardName;
    private Integer status;
    private Date createTime;
    private Date updateTime;
}
