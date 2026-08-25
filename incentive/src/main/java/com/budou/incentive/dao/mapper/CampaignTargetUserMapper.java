package com.budou.incentive.dao.mapper;

import com.budou.incentive.dao.model.CampaignTargetUser;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

import java.util.List;

@Mapper
public interface CampaignTargetUserMapper {

    String SELECT_COLUMNS = "id, execution_id as executionId, activity_id as activityId, " +
            "user_id as userId, experiment_group as experimentGroup, " +
            "delivery_channel as deliveryChannel, points_snapshot as pointsSnapshot, " +
            "last_active_at_snapshot as lastActiveAtSnapshot, data_source as dataSource, " +
            "assigned_at as assignedAt";

    @Insert({
            "<script>",
            "insert ignore into campaign_target_user(",
            "execution_id, activity_id, user_id, experiment_group, delivery_channel, ",
            "points_snapshot, last_active_at_snapshot, data_source, assigned_at) values ",
            "<foreach collection='targets' item='target' separator=','>",
            "(#{target.executionId}, #{target.activityId}, #{target.userId}, ",
            "#{target.experimentGroup}, #{target.deliveryChannel}, #{target.pointsSnapshot}, ",
            "#{target.lastActiveAtSnapshot}, #{target.dataSource}, #{target.assignedAt})",
            "</foreach>",
            "</script>"
    })
    int insertBatch(@Param("targets") List<CampaignTargetUser> targets);

    @Select("select " + SELECT_COLUMNS +
            " from campaign_target_user where execution_id = #{executionId} order by user_id")
    List<CampaignTargetUser> selectByExecutionId(@Param("executionId") Long executionId);

    @Select("select count(*) from campaign_target_user " +
            "where activity_id = #{activityId} and data_source <> 'REAL'")
    int countNonRealByActivityId(@Param("activityId") Long activityId);
}
