package com.budou.incentive.dao.mapper;

import com.budou.incentive.dao.model.AwardConfig;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;

import java.util.Date;
import java.util.List;

@Mapper
public interface AwardConfigMapper {
    @Select("select * from award_config where awardId = #{awardId}")
    AwardConfig selectAwardInfo(Long awardId);

    @Update("update award_config set inventory = #{inventory}, updateTime = #{updateTime}" +
            "where awardId = #{awardId}")
    int update(Long awardId, Integer inventory, Date updateTime);

    @Insert("insert into award_config values(#{awardId}, #{coverUrl},#{name},#{awardType},#{inventory}," +
            "#{price},#{startTime},#{endTime},#{createTime},#{updateTime},#{initInventory})")
    int insert(AwardConfig awardConfig);

    @Select("select endTime from award_config where awardId = #{awardId}")
    Date selectEndTime(Long awardId);

    @Select("select startTime from award_config where awardId = #{awardId}")
    Date selectStartTime(Long awardId);

    @Select("select price from award_config where awardId = #{awardId}")
    Integer selectPrice(Long awardId);

    @Select("select inventory from award_config where awardId = #{awardId}")
    Integer selectInventory(Long awardId);

    @Select("select isOverSell from award_config where awardId = #{awardId}")
    Integer selectIsOverSell(Long awardId);

    @Update("update award_config set inventory = #{inventory} where awardId = #{awardId}")
    void updateInventory(AwardConfig awardConfig);

    @Select("select * from award_config " +
            "where (startTime is null or startTime <= #{now}) " +
            "and (endTime is null or endTime >= #{now}) " +
            "and inventory > 0 order by price asc, awardId asc")
    List<AwardConfig> selectActiveAwards(@Param("now") Date now);
}
