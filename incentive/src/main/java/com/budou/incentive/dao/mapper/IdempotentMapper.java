package com.budou.incentive.dao.mapper;

import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Select;

@Mapper
public interface IdempotentMapper {

    @Select("select count(*) from idempotent_table where idempotent_key = #{idempotentKey}")
    Integer select(String idempotentKey);
}
