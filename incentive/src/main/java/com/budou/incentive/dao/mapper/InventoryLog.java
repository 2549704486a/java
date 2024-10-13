package com.budou.incentive.dao.mapper;

import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;

import java.util.Date;

@Mapper
public interface InventoryLog {
    @Insert("insert into inventory_log values(#{userId}, #{awardId},#{inventory},#{splitId},#{createTime})")
    void insertLog(Long userId, Long awardId, Integer inventory, Long splitId, Date createTime);
}
