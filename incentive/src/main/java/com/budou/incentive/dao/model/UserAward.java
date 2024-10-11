package com.budou.incentive.dao.model;

import lombok.AllArgsConstructor;
import lombok.Data;

import java.time.LocalDateTime;
import java.util.Date;
@AllArgsConstructor
@Data
public class UserAward {

    private Long id;

    private Long userId;

    private Long awardId;

    private Integer status;

    private Date createTime;

    private Date updateTime;

    public UserAward() {

    }
}
