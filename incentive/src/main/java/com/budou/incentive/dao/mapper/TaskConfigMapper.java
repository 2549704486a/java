package com.budou.incentive.dao.mapper;

import com.budou.incentive.dao.model.TaskConfig;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

import java.util.Date;
import java.util.List;

@Mapper
public interface TaskConfigMapper {
    @Select("select currency from task_config where taskId = #{taskId}")
    Integer getTaskCurrency(Long taskId);

    @Select("select * from task_config where taskId = #{taskId}")
    TaskConfig selectTask(Long taskId);

    @Select("select * from task_config " +
            "where (startTime is null or startTime <= #{now}) " +
            "and (endTime is null or endTime >= #{now}) " +
            "order by currency desc, taskId asc")
    List<TaskConfig> selectActiveTasks(@Param("now") Date now);
}
