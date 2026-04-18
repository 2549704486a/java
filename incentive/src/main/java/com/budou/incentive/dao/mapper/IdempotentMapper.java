package com.budou.incentive.dao.mapper;

import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Select;

@Mapper
public interface IdempotentMapper {

    @Select("select count(*) from idempotent_table where idempotent_key = #{idempotentKey}")
    Integer select(String idempotentKey);

    @Insert("insert into idempotent_table (idempotent_key) values (#{idempotentKey})")
    Integer insert(String idempotentKey);
}
