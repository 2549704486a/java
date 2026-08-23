package com.budou.incentive.dao.mapper;

import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;

import java.util.Date;

@Mapper
public interface CampaignPlanAuditMapper {

    @Insert("insert into campaign_plan_audit(" +
            "draft_id, action, from_status, to_status, operator_id, comment, created_at) values(" +
            "#{draftId}, #{action}, #{fromStatus}, #{toStatus}, #{operatorId}, #{comment}, #{createdAt})")
    int insert(@Param("draftId") Long draftId,
               @Param("action") String action,
               @Param("fromStatus") String fromStatus,
               @Param("toStatus") String toStatus,
               @Param("operatorId") String operatorId,
               @Param("comment") String comment,
               @Param("createdAt") Date createdAt);
}
