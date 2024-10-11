package com.budou.incentive.dao.mapper;

import com.budou.incentive.dao.model.AwardConfig;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;

import java.util.Date;

@Mapper
public interface AwardConfigMapper {
    @Select("select * from award_config where awardId = #{awardId}")
    AwardConfig selectAwardInfo(Long awardId);

    @Update("update award_config set inventory = #{inventory} where awardId = #{awardId}")
    int update(AwardConfig awardConfig);

    @Insert("insert into award_config values(#{awardId}, #{coverUrl},#{name},#{awardType},#{inventory}," +
            "#{price},#{startTime},#{endTime},#{createTime},#{updateTime},#{initInventory})")
    int insert(AwardConfig awardConfig);

    @Select("select endTime from award_config where awardId = #{awardId}")
    Date selectEndTime(Long awardId);

    @Select("select price from award_config where awardId = #{awardId}")
    Integer selectPrice(Long awardId);

    @Select("select inventory from award_config where awardId = #{awardId}")
    Integer selectInventory(Long awardId);

    @Select("select isOverSell from award_config where awardId = #{awardId}")
    Integer selectIsOverSell(Long awardId);

    @Update("update award_config set inventory = #{inventory} where awardId = #{awardId}")
    void updateInventory(AwardConfig awardConfig);
}
