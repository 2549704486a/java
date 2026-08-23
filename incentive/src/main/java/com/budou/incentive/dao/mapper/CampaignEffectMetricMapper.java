package com.budou.incentive.dao.mapper;

import com.budou.incentive.dao.model.CampaignEffectMetric;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Options;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

import java.util.List;

@Mapper
public interface CampaignEffectMetricMapper {

    String SELECT_COLUMNS = "id, activity_id as activityId, metric_name as metricName, " +
            "metric_value as metricValue, sample_size as sampleSize, measured_at as measuredAt, " +
            "source_ref as sourceRef, recorded_by as recordedBy, created_at as createdAt";

    @Insert("insert into campaign_effect_metric(" +
            "activity_id, metric_name, metric_value, sample_size, measured_at, source_ref, " +
            "recorded_by, created_at) values(" +
            "#{activityId}, #{metricName}, #{metricValue}, #{sampleSize}, #{measuredAt}, " +
            "#{sourceRef}, #{recordedBy}, #{createdAt})")
    @Options(useGeneratedKeys = true, keyProperty = "id")
    int insert(CampaignEffectMetric metric);

    @Select("select " + SELECT_COLUMNS +
            " from campaign_effect_metric where activity_id = #{activityId} " +
            "order by measured_at desc, id desc")
    List<CampaignEffectMetric> selectByActivityId(@Param("activityId") Long activityId);
}
