package com.budou.incentive.dao.mapper;

import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Update;

@Mapper
public interface UserTaskMapper {
    @Update("update user_task set completedTasks = completedTasks + 1 " +
            "where userId = #{userId}")
    int updateCompletedTasks(Long userId);
}
