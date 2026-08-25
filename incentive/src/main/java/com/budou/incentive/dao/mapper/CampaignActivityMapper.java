package com.budou.incentive.dao.mapper;

import com.budou.incentive.dao.model.CampaignActivity;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Options;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;

import java.util.Date;
import java.util.List;

@Mapper
public interface CampaignActivityMapper {

    String SELECT_COLUMNS = "id, draft_id as draftId, objective, " +
            "target_segment_key as targetSegmentKey, budget_amount_cents as budgetAmountCents, " +
            "points_issuance_cap as pointsIssuanceCap, start_at as startAt, end_at as endAt, " +
            "plan_json as planJson, status, published_by as publishedBy, published_at as publishedAt, " +
            "created_at as createdAt, updated_at as updatedAt";

    @Insert("insert into campaign_activity(" +
            "draft_id, objective, target_segment_key, budget_amount_cents, points_issuance_cap, " +
            "start_at, end_at, plan_json, status, published_by, published_at, created_at, updated_at) values(" +
            "#{draftId}, #{objective}, #{targetSegmentKey}, #{budgetAmountCents}, #{pointsIssuanceCap}, " +
            "#{startAt}, #{endAt}, #{planJson}, #{status}, #{publishedBy}, #{publishedAt}, " +
            "#{createdAt}, #{updatedAt})")
    @Options(useGeneratedKeys = true, keyProperty = "id")
    int insert(CampaignActivity activity);

    @Select("select " + SELECT_COLUMNS + " from campaign_activity where id = #{id}")
    CampaignActivity selectById(@Param("id") Long id);

    @Select("select " + SELECT_COLUMNS + " from campaign_activity where draft_id = #{draftId}")
    CampaignActivity selectByDraftId(@Param("draftId") Long draftId);

    @Select("select " + SELECT_COLUMNS +
            " from campaign_activity order by published_at desc, id desc limit #{limit}")
    List<CampaignActivity> selectRecent(@Param("limit") int limit);

    @Select("select " + SELECT_COLUMNS + " from campaign_activity a " +
            "where a.status in ('SCHEDULED', 'ACTIVE') " +
            "and a.start_at <= #{now} and a.end_at > #{now} " +
            "and not exists (select 1 from campaign_execution e where e.activity_id = a.id) " +
            "order by a.start_at, a.id limit #{limit}")
    List<CampaignActivity> selectDueWithoutExecution(
            @Param("now") Date now,
            @Param("limit") int limit);

    @Update("update campaign_activity set status = 'ACTIVE', updated_at = #{updatedAt} " +
            "where id = #{id} and status = 'SCHEDULED'")
    int markActive(@Param("id") Long id, @Param("updatedAt") Date updatedAt);
}
