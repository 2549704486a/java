package com.budou.incentive.dao.mapper;

import com.budou.incentive.dao.model.UserCurrency;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;

@Mapper
public interface UserCurrencyMapper {
    @Select("select * from user_currency where userId = #{userId}")
    UserCurrency selectUserInfo(Long userId);

    @Update("update user_currency set currency = #{currency} where userId = #{userId}")
    int updateCurrency(UserCurrency userCurrency);

    @Select("select currency from user_currency where userId = #{userId}")
    Integer selectCurrency(Long userId);
}
