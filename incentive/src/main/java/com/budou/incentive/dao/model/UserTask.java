package com.budou.incentive.dao.model;

import lombok.AllArgsConstructor;
import lombok.Data;

/**
 * @program: incentive
 * @description:
 * @author: 阿伟
 * @create: 2024-10-15 10:29
 **/
@AllArgsConstructor
@Data
public class UserTask {
    private Long id;

    private Long userId;

    private Integer completedTasks;
}
