package com.budou.incentive.dao.mapper;

import com.budou.incentive.dao.model.CampaignEvent;
import com.budou.incentive.dao.model.CampaignEventCandidate;
import com.budou.incentive.dao.model.CampaignEventCount;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

import java.util.List;

@Mapper
public interface CampaignEventMapper {

    @Insert("insert ignore into campaign_event(" +
            "event_key, activity_id, user_id, event_type, source, occurred_at, " +
            "metadata_json, created_at) values(" +
            "#{eventKey}, #{activityId}, #{userId}, #{eventType}, #{source}, " +
            "#{occurredAt}, #{metadataJson}, #{createdAt})")
    int insertIfAbsent(CampaignEvent event);

    @Select("select n.activity_id as activityId, n.user_id as userId, n.id as referenceId, " +
            "n.created_at as occurredAt, " +
            "case when t.data_source = 'REAL' then 'REAL' else 'SIMULATED' end as source " +
            "from user_notification n " +
            "join campaign_target_user t on t.activity_id = n.activity_id and t.user_id = n.user_id " +
            "left join campaign_event e on e.event_key = concat('notification:delivered:', n.id) " +
            "where e.id is null order by n.id limit #{limit}")
    List<CampaignEventCandidate> selectUnprojectedDelivered(@Param("limit") int limit);

    @Select("select n.activity_id as activityId, n.user_id as userId, n.id as referenceId, " +
            "n.read_at as occurredAt, " +
            "case when t.data_source = 'REAL' then 'REAL' else 'SIMULATED' end as source " +
            "from user_notification n " +
            "join campaign_target_user t on t.activity_id = n.activity_id and t.user_id = n.user_id " +
            "left join campaign_event e on e.event_key = concat('notification:view:', n.id) " +
            "where n.read_at is not null and e.id is null order by n.id limit #{limit}")
    List<CampaignEventCandidate> selectUnprojectedViews(@Param("limit") int limit);

    @Select("select n.activity_id as activityId, n.user_id as userId, n.id as referenceId, " +
            "n.clicked_at as occurredAt, " +
            "case when t.data_source = 'REAL' then 'REAL' else 'SIMULATED' end as source " +
            "from user_notification n " +
            "join campaign_target_user t on t.activity_id = n.activity_id and t.user_id = n.user_id " +
            "left join campaign_event e on e.event_key = concat('notification:click:', n.id) " +
            "where n.clicked_at is not null and e.id is null order by n.id limit #{limit}")
    List<CampaignEventCandidate> selectUnprojectedClicks(@Param("limit") int limit);

    @Select("select t.activity_id as activityId, f.userId as userId, f.id as referenceId, " +
            "f.finishTime as occurredAt, " +
            "case when t.data_source = 'REAL' then 'REAL' else 'SIMULATED' end as source " +
            "from campaign_target_user t " +
            "join finish_task_record f on f.userId = t.user_id and f.finishTime >= t.assigned_at " +
            "left join campaign_event e on e.event_key = " +
            "concat('task:complete:', t.activity_id, ':', f.id) " +
            "where e.id is null order by f.id limit #{limit}")
    List<CampaignEventCandidate> selectUnprojectedTaskCompletions(@Param("limit") int limit);

    @Select("select t.activity_id as activityId, a.userId as userId, a.id as referenceId, " +
            "coalesce(a.updateTime, a.createTime) as occurredAt, " +
            "case when t.data_source = 'REAL' then 'REAL' else 'SIMULATED' end as source " +
            "from campaign_target_user t " +
            "join user_award a on a.userId = t.user_id and a.status = 1 " +
            "and coalesce(a.updateTime, a.createTime) >= t.assigned_at " +
            "left join campaign_event e on e.event_key = " +
            "concat('exchange:success:', t.activity_id, ':', a.id) " +
            "where e.id is null order by a.id limit #{limit}")
    List<CampaignEventCandidate> selectUnprojectedExchanges(@Param("limit") int limit);

    @Select("select t.experiment_group as experimentGroup, e.event_type as eventType, " +
            "count(distinct e.user_id) as eventUsers " +
            "from campaign_target_user t join campaign_event e " +
            "on e.activity_id = t.activity_id and e.user_id = t.user_id " +
            "where t.activity_id = #{activityId} " +
            "group by t.experiment_group, e.event_type")
    List<CampaignEventCount> countDistinctUsersByGroupAndType(
            @Param("activityId") Long activityId);
}
