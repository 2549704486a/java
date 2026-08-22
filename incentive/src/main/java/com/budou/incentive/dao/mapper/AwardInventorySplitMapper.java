package com.budou.incentive.dao.mapper;

import com.budou.incentive.dao.model.AwardInventorySplit;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;

import java.util.List;

@Mapper
public interface AwardInventorySplitMapper {

    @Select("select * from award_inventory_split where awardId = #{awardId} and inventory > 0")
    List<AwardInventorySplit> select(Long awardId);

    @Update("update award_inventory_split set inventory = (inventory - 1) " +
            "where splitId = #{splitId} and awardId = #{awardId} and inventory > 0")
    int updateInventory(AwardInventorySplit awardInventorySplit);

    @Select("select coalesce(sum(inventory), 0) from award_inventory_split where awardId = #{awardId}")
    long selectTotalInventory(Long awardId);

}
