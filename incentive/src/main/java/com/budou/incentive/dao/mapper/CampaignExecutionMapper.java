package com.budou.incentive.dao.mapper;

import com.budou.incentive.dao.model.CampaignExecution;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Options;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;

import java.util.Date;

@Mapper
public interface CampaignExecutionMapper {

    String SELECT_COLUMNS = "id, activity_id as activityId, status, " +
            "treatment_ratio_bps as treatmentRatioBps, total_users as totalUsers, " +
            "treatment_users as treatmentUsers, control_users as controlUsers, " +
            "sent_users as sentUsers, failed_users as failedUsers, version, " +
            "started_at as startedAt, completed_at as completedAt, last_error as lastError, " +
            "created_at as createdAt, updated_at as updatedAt";

    @Insert("insert ignore into campaign_execution(" +
            "activity_id, status, treatment_ratio_bps, total_users, treatment_users, " +
            "control_users, sent_users, failed_users, version, created_at, updated_at) values(" +
            "#{activityId}, #{status}, #{treatmentRatioBps}, 0, 0, 0, 0, 0, 1, " +
            "#{createdAt}, #{updatedAt})")
    @Options(useGeneratedKeys = true, keyProperty = "id")
    int insertIfAbsent(CampaignExecution execution);

    @Select("select " + SELECT_COLUMNS + " from campaign_execution where id = #{id}")
    CampaignExecution selectById(@Param("id") Long id);

    @Select("select " + SELECT_COLUMNS +
            " from campaign_execution where activity_id = #{activityId}")
    CampaignExecution selectByActivityId(@Param("activityId") Long activityId);

    @Update("update campaign_execution set status = 'RUNNING', total_users = #{totalUsers}, " +
            "treatment_users = #{treatmentUsers}, control_users = #{controlUsers}, " +
            "started_at = #{startedAt}, updated_at = #{updatedAt}, version = version + 1 " +
            "where id = #{id} and status = 'PENDING'")
    int markRunning(@Param("id") Long id,
                    @Param("totalUsers") int totalUsers,
                    @Param("treatmentUsers") int treatmentUsers,
                    @Param("controlUsers") int controlUsers,
                    @Param("startedAt") Date startedAt,
                    @Param("updatedAt") Date updatedAt);

    @Update("update campaign_execution set status = 'COMPLETED', total_users = 0, " +
            "treatment_users = 0, control_users = 0, started_at = #{completedAt}, " +
            "completed_at = #{completedAt}, updated_at = #{completedAt}, version = version + 1 " +
            "where id = #{id} and status = 'PENDING'")
    int markEmptyCompleted(@Param("id") Long id, @Param("completedAt") Date completedAt);
}
