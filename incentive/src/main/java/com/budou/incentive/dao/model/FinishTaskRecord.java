package com.budou.incentive.dao.model;

import lombok.AllArgsConstructor;
import lombok.Data;

import java.util.Date;

/**
 * @program: incentive
 * @description:
 * @author: 阿伟
 * @create: 2024-10-15 18:36
 **/
@AllArgsConstructor
@Data
public class FinishTaskRecord {
    private Long id;

    private Long userId;

    private Long taskId;

    private Integer status;

    private Date finishTime;

    public FinishTaskRecord() {

    }
}
