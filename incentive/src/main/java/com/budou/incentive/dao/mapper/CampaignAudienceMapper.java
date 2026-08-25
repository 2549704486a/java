package com.budou.incentive.dao.mapper;

import com.budou.incentive.dao.model.CampaignAudienceUser;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

import java.util.Date;
import java.util.List;

@Mapper
public interface CampaignAudienceMapper {

    String SELECT_USER_FACTS = "select uc.userId as userId, cast(uc.currency as signed) as points, " +
            "uas.last_active_at as lastActiveAt, coalesce(uas.source, 'REAL') as dataSource " +
            "from user_currency uc left join user_activity_summary uas on uas.user_id = uc.userId ";

    @Select(SELECT_USER_FACTS + "order by uc.userId")
    List<CampaignAudienceUser> selectAllUsers();

    @Select(SELECT_USER_FACTS +
            "where uc.currency >= #{minimumPoints} order by uc.userId")
    List<CampaignAudienceUser> selectUsersWithMinimumPoints(
            @Param("minimumPoints") int minimumPoints);

    @Select(SELECT_USER_FACTS +
            "where uas.last_active_at >= #{activeSince} order by uc.userId")
    List<CampaignAudienceUser> selectUsersActiveSince(@Param("activeSince") Date activeSince);

    @Select(SELECT_USER_FACTS +
            "where uas.last_login_at is not null and uas.last_login_at < #{inactiveBefore} " +
            "order by uc.userId")
    List<CampaignAudienceUser> selectUsersInactiveBefore(
            @Param("inactiveBefore") Date inactiveBefore);

    @Select("select count(*) from user_currency")
    long countAllUsers();

    @Select("select count(*) from user_currency where currency >= #{minimumPoints}")
    long countUsersWithMinimumPoints(@Param("minimumPoints") int minimumPoints);

    @Select("select count(*) from user_currency uc " +
            "join user_activity_summary uas on uas.user_id = uc.userId " +
            "where uas.last_active_at >= #{activeSince}")
    long countUsersActiveSince(@Param("activeSince") Date activeSince);

    @Select("select count(*) from user_currency uc " +
            "join user_activity_summary uas on uas.user_id = uc.userId " +
            "where uas.last_login_at is not null and uas.last_login_at < #{inactiveBefore}")
    long countUsersInactiveBefore(@Param("inactiveBefore") Date inactiveBefore);
}
