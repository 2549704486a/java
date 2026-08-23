package com.budou.incentive.dao.mapper;

import com.budou.incentive.dao.model.CampaignActivity;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Options;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

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
}
