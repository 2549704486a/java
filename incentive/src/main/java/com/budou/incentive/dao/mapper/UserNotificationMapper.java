package com.budou.incentive.dao.mapper;

import com.budou.incentive.dao.model.UserNotification;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Options;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;

import java.util.Date;
import java.util.List;

@Mapper
public interface UserNotificationMapper {

    String SELECT_COLUMNS = "id, delivery_task_id as deliveryTaskId, activity_id as activityId, " +
            "user_id as userId, title, content, status, read_at as readAt, " +
            "clicked_at as clickedAt, created_at as createdAt, updated_at as updatedAt";

    @Insert("insert ignore into user_notification(" +
            "delivery_task_id, activity_id, user_id, title, content, status, created_at, updated_at) " +
            "values(#{deliveryTaskId}, #{activityId}, #{userId}, #{title}, #{content}, " +
            "#{status}, #{createdAt}, #{updatedAt})")
    @Options(useGeneratedKeys = true, keyProperty = "id")
    int insertIfAbsent(UserNotification notification);

    @Select("select " + SELECT_COLUMNS + " from user_notification " +
            "where user_id = #{userId} order by created_at desc, id desc limit #{limit}")
    List<UserNotification> selectByUserId(@Param("userId") Long userId,
                                          @Param("limit") int limit);

    @Select("select " + SELECT_COLUMNS + " from user_notification " +
            "where id = #{id} and user_id = #{userId}")
    UserNotification selectOwned(@Param("id") Long id, @Param("userId") Long userId);

    @Update("update user_notification set status = 'READ', read_at = #{readAt}, " +
            "updated_at = #{readAt} where id = #{id} and user_id = #{userId} " +
            "and status = 'UNREAD'")
    int markRead(@Param("id") Long id,
                 @Param("userId") Long userId,
                 @Param("readAt") Date readAt);

    @Update("update user_notification set status = 'CLICKED', " +
            "read_at = coalesce(read_at, #{clickedAt}), clicked_at = #{clickedAt}, " +
            "updated_at = #{clickedAt} where id = #{id} and user_id = #{userId} " +
            "and status in ('UNREAD', 'READ')")
    int markClicked(@Param("id") Long id,
                    @Param("userId") Long userId,
                    @Param("clickedAt") Date clickedAt);
}
