package com.budou.incentive.dao.mapper;

import com.budou.incentive.dao.model.CampaignDeliveryTask;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;

import java.util.Date;
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

    @Select("select " + SELECT_COLUMNS + " from campaign_delivery_task where id = #{id}")
    CampaignDeliveryTask selectById(@Param("id") Long id);

    @Select("select id from campaign_delivery_task " +
            "where channel = #{channel} and status in ('PENDING', 'RETRY_WAIT') " +
            "and next_attempt_at <= #{now} order by id limit #{limit}")
    List<Long> selectDispatchableIds(@Param("channel") String channel,
                                     @Param("now") Date now,
                                     @Param("limit") int limit);

    @Update("update campaign_delivery_task set status = 'PROCESSING', claimed_at = #{claimedAt}, " +
            "updated_at = #{claimedAt} where id = #{id} " +
            "and status in ('PENDING', 'RETRY_WAIT') and next_attempt_at <= #{claimedAt}")
    int claim(@Param("id") Long id, @Param("claimedAt") Date claimedAt);

    @Update("update campaign_delivery_task set status = case " +
            "when attempt_count + 1 >= max_attempts then 'DEAD' else 'RETRY_WAIT' end, " +
            "attempt_count = attempt_count + 1, next_attempt_at = #{nextAttemptAt}, " +
            "last_error = #{lastError}, updated_at = #{updatedAt} " +
            "where id = #{id} and status = 'PROCESSING'")
    int markDispatchFailure(@Param("id") Long id,
                            @Param("nextAttemptAt") Date nextAttemptAt,
                            @Param("lastError") String lastError,
                            @Param("updatedAt") Date updatedAt);

    @Update("update campaign_delivery_task set status = 'RETRY_WAIT', " +
            "next_attempt_at = #{recoveredAt}, last_error = 'dispatch-timeout', " +
            "updated_at = #{recoveredAt} where channel = #{channel} and status = 'PROCESSING' " +
            "and claimed_at < #{staleBefore}")
    int recoverStaleProcessing(@Param("channel") String channel,
                               @Param("staleBefore") Date staleBefore,
                               @Param("recoveredAt") Date recoveredAt);

    @Update("update campaign_delivery_task set status = 'SENT', sent_at = #{sentAt}, " +
            "last_error = null, updated_at = #{sentAt} where id = #{id} " +
            "and status in ('PROCESSING', 'PENDING', 'RETRY_WAIT')")
    int markSent(@Param("id") Long id, @Param("sentAt") Date sentAt);
}
