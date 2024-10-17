package com.budou.incentive.dao.model;

import lombok.AllArgsConstructor;
import lombok.Data;

import java.util.Date;

/**
 * @program: incentive
 * @description:
 * @author: 阿伟
 * @create: 2024-10-15 10:28
 **/
@AllArgsConstructor
@Data
public class TaskConfig {
    private Long taskId;

    private String taskName;

    private Integer currency;

    private Date StartTime;

    private Date endTime;

    private Integer Type;

    private String Description;
}
