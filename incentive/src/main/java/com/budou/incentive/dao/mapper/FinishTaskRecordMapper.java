package com.budou.incentive.dao.mapper;

import com.budou.incentive.dao.model.FinishTaskRecord;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;

@Mapper
public interface FinishTaskRecordMapper {
    @Select("select status from finish_task_record where userId = #{userId} and taskId = #{taskId}")
    Integer selectTaskStatus(Long userId, Long taskId);

    @Update("update finish_task_record set status = 1 where userId = #{userId} and taskId = #{taskId}")
    Integer updateTaskStatus(Long userId, Long taskId);

    @Insert("insert into finish_task_record (userId, taskId, status, finishTime)" +
            "values (#{userId}, #{taskId}, #{status}, #{finishTime})")
    int insertFinishTask(FinishTaskRecord finishTaskRecord);
}
