package com.budou.incentive.dao.mapper;

import com.budou.incentive.dao.model.CampaignPlanDraft;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Options;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;

import java.util.Date;
import java.util.List;

@Mapper
public interface CampaignPlanDraftMapper {

    String SELECT_COLUMNS = "id, draft_key as draftKey, version, operator_id as operatorId, " +
            "objective, target_segment_key as targetSegmentKey, target_segment as targetSegment, " +
            "budget_amount_cents as budgetAmountCents, points_issuance_cap as pointsIssuanceCap, " +
            "start_at as startAt, end_at as endAt, plan_json as planJson, status, " +
            "reviewer_id as reviewerId, review_comment as reviewComment, reviewed_at as reviewedAt, " +
            "published_by as publishedBy, published_at as publishedAt, " +
            "created_at as createdAt, updated_at as updatedAt";

    @Insert("insert into campaign_plan_draft(" +
            "draft_key, version, operator_id, objective, target_segment_key, target_segment, " +
            "budget_amount_cents, points_issuance_cap, start_at, end_at, plan_json, status, " +
            "created_at, updated_at) values(" +
            "#{draftKey}, #{version}, #{operatorId}, #{objective}, #{targetSegmentKey}, " +
            "#{targetSegment}, #{budgetAmountCents}, #{pointsIssuanceCap}, #{startAt}, #{endAt}, " +
            "#{planJson}, #{status}, #{createdAt}, #{updatedAt})")
    @Options(useGeneratedKeys = true, keyProperty = "id")
    int insert(CampaignPlanDraft draft);

    @Select("select " + SELECT_COLUMNS + " from campaign_plan_draft where id = #{id}")
    CampaignPlanDraft selectById(@Param("id") Long id);

    @Select("select " + SELECT_COLUMNS + " from campaign_plan_draft where draft_key = #{draftKey}")
    CampaignPlanDraft selectByDraftKey(@Param("draftKey") String draftKey);

    @Select("select " + SELECT_COLUMNS +
            " from campaign_plan_draft order by updated_at desc, id desc limit #{limit}")
    List<CampaignPlanDraft> selectRecent(@Param("limit") int limit);

    @Update("update campaign_plan_draft set status = 'PENDING_REVIEW', version = version + 1, " +
            "updated_at = #{updatedAt} where id = #{id} and status = 'DRAFT' and version = #{version}")
    int submitForReview(@Param("id") Long id,
                        @Param("version") Integer version,
                        @Param("updatedAt") Date updatedAt);

    @Update("update campaign_plan_draft set status = #{newStatus}, version = version + 1, " +
            "reviewer_id = #{reviewerId}, review_comment = #{comment}, reviewed_at = #{reviewedAt}, " +
            "updated_at = #{reviewedAt} where id = #{id} and status = 'PENDING_REVIEW' " +
            "and version = #{version}")
    int review(@Param("id") Long id,
               @Param("version") Integer version,
               @Param("newStatus") String newStatus,
               @Param("reviewerId") String reviewerId,
               @Param("comment") String comment,
               @Param("reviewedAt") Date reviewedAt);

    @Update("update campaign_plan_draft set status = 'PUBLISHED', version = version + 1, " +
            "published_by = #{publishedBy}, published_at = #{publishedAt}, updated_at = #{publishedAt} " +
            "where id = #{id} and status = 'APPROVED' and version = #{version}")
    int markPublished(@Param("id") Long id,
                      @Param("version") Integer version,
                      @Param("publishedBy") String publishedBy,
                      @Param("publishedAt") Date publishedAt);
}
