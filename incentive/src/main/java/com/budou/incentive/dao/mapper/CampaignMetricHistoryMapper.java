package com.budou.incentive.dao.mapper;

import com.budou.incentive.dao.model.CampaignMetricHistory;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

@Mapper
public interface CampaignMetricHistoryMapper {

    @Select("select * from campaign_metric_history " +
            "where segment_key = #{segmentKey} and metric_name = #{metricName} " +
            "order by measured_at desc, id desc limit 1")
    CampaignMetricHistory selectLatest(@Param("segmentKey") String segmentKey,
                                       @Param("metricName") String metricName);
}
