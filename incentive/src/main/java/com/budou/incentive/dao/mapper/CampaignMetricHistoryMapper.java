package com.budou.incentive.dao.mapper;

import com.budou.incentive.dao.model.CampaignMetricHistory;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Options;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

@Mapper
public interface CampaignMetricHistoryMapper {

    @Insert("insert into campaign_metric_history(" +
            "segment_key, metric_name, metric_value, sample_size, measured_at, source_ref) values(" +
            "#{segmentKey}, #{metricName}, #{metricValue}, #{sampleSize}, #{measuredAt}, #{sourceRef})")
    @Options(useGeneratedKeys = true, keyProperty = "id")
    int insert(CampaignMetricHistory metric);

    @Select("select id, segment_key as segmentKey, metric_name as metricName, " +
            "metric_value as metricValue, sample_size as sampleSize, measured_at as measuredAt, " +
            "source_ref as sourceRef from campaign_metric_history " +
            "where segment_key = #{segmentKey} and metric_name = #{metricName} " +
            "order by measured_at desc, id desc limit 1")
    CampaignMetricHistory selectLatest(@Param("segmentKey") String segmentKey,
                                       @Param("metricName") String metricName);
}
