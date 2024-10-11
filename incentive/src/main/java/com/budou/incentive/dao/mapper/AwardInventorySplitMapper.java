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

    @Update("update award_inventory_split set inventory = #{inventory} where id = #{id}")
    int updateInventory(AwardInventorySplit awardInventorySplit);
}
