package com.budou.incentive.dao.mapper;

import com.budou.incentive.dao.model.CampaignDeliveryTask;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

import java.util.List;

@Mapper
public interface CampaignDeliveryTaskMapper {

    String SELECT_COLUMNS = "id, execution_id as executionId, activity_id as activityId, " +
            "target_user_id as targetUserId, user_id as userId, channel, status, " +
            "attempt_count as attemptCount, max_attempts as maxAttempts, " +
            "next_attempt_at as nextAttemptAt, claimed_at as claimedAt, sent_at as sentAt, " +
            "last_error as lastError, created_at as createdAt, updated_at as updatedAt";

    @Insert({
            "<script>",
            "insert ignore into campaign_delivery_task(",
            "execution_id, activity_id, target_user_id, user_id, channel, status, ",
            "attempt_count, max_attempts, next_attempt_at, created_at, updated_at) values ",
            "<foreach collection='tasks' item='task' separator=','>",
            "(#{task.executionId}, #{task.activityId}, #{task.targetUserId}, #{task.userId}, ",
            "#{task.channel}, #{task.status}, #{task.attemptCount}, #{task.maxAttempts}, ",
            "#{task.nextAttemptAt}, #{task.createdAt}, #{task.updatedAt})",
            "</foreach>",
            "</script>"
    })
    int insertBatch(@Param("tasks") List<CampaignDeliveryTask> tasks);

    @Select("select " + SELECT_COLUMNS +
            " from campaign_delivery_task where execution_id = #{executionId} order by id")
    List<CampaignDeliveryTask> selectByExecutionId(@Param("executionId") Long executionId);
}
