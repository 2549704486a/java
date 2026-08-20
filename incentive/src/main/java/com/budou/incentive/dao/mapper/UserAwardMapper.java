package com.budou.incentive.dao.mapper;
import com.budou.incentive.dao.model.UserAward;
import org.apache.ibatis.annotations.*;

@Mapper
public interface UserAwardMapper {
    // 使用@Select注解指定要执行的SQL查询语句
    // 该方法根据用户ID和奖励ID查询用户奖励信息
    @Select("select * from user_award where userId=#{userId} and awardId = #{awardId}")
    UserAward selectUserAward(Long userId,Long awardId);

    @Insert("insert into user_award (id, userId, awardId, status, createTime, updateTime) " +
            " values(#{id}, #{userId},#{awardId},#{status},#{createTime},#{updateTime})")
    int insert(UserAward userAward);

    @Update("update user_award set status = #{status}, updateTime = #{updateTime} " +
            "where id = #{id}")
    int updateStatus(UserAward userAward);

    @Select("select status from user_award where userId=#{userId} and awardId = #{awardId}")
    Integer selectStatus(Long userId, Long awardId);

    @Select("select status from user_award where id = #{id}")
    Integer selectStatusById(Long id);

    @Delete("delete from user_award where userId = #{userId} and awardId = #{awardId}")
    Integer delete(Long userId, Long awardId);

    @Update("update user_award set status = -1 where id = #{id}")
    void updateStatusFail(Long id);
}
