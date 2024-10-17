package com.budou.incentive.dao.mapper;

import com.budou.incentive.dao.model.TaskConfig;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Select;

@Mapper
public interface TaskConfigMapper {
    @Select("select currency from task_config where taskId = #{taskId}")
    Integer getTaskCurrency(Long taskId);

    @Select("select * from task_config where taskId = #{taskId}")
    TaskConfig selectTask(Long taskId);
}
