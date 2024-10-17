package com.budou.incentive.dao.mapper;

import com.budou.incentive.dao.model.AddCurrencyRecord;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;

@Mapper
public interface AddCurrencyRecordMapper {

    @Insert("insert into add_currency_record (userId, currency, afterCurrency, description, requestId, createTime) " +
            "values (#{userId}, #{currency}, #{afterCurrency}, #{description}, #{requestId}, #{createTime})")
    void insert(AddCurrencyRecord addCurrencyRecord);
}
