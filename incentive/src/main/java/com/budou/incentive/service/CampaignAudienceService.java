package com.budou.incentive.service;

import com.budou.incentive.dao.mapper.CampaignAudienceMapper;
import com.budou.incentive.dao.model.CampaignAudienceUser;
import com.budou.incentive.dto.agent.CampaignSegmentSnapshotView;
import org.springframework.stereotype.Service;

import java.time.temporal.ChronoUnit;
import java.util.Date;
import java.util.List;

/**
 * 统一活动规划与执行使用的客群口径，避免同一个客群在两个入口中含义不同。
 */
@Service
public class CampaignAudienceService {

    public static final String ALL_USERS = "ALL_USERS";
    public static final String POINTS_AT_LEAST_500 = "POINTS_AT_LEAST_500";
    public static final String ACTIVE_LAST_7_DAYS = "ACTIVE_LAST_7_DAYS";
    public static final String INACTIVE_30_DAYS = "INACTIVE_30_DAYS";

    private static final int MINIMUM_POINTS = 500;

    private final CampaignAudienceMapper audienceMapper;

    public CampaignAudienceService(CampaignAudienceMapper audienceMapper) {
        this.audienceMapper = audienceMapper;
    }

    public CampaignSegmentSnapshotView getSegmentSnapshot(String segmentKey, Date now) {
        if (ALL_USERS.equals(segmentKey)) {
            return snapshot(ALL_USERS, "全部积分用户", audienceMapper.countAllUsers(), now);
        }
        if (POINTS_AT_LEAST_500.equals(segmentKey)) {
            return snapshot(
                    POINTS_AT_LEAST_500,
                    "当前积分不少于 500 的用户",
                    audienceMapper.countUsersWithMinimumPoints(MINIMUM_POINTS),
                    now
            );
        }
        if (ACTIVE_LAST_7_DAYS.equals(segmentKey)) {
            Date activeSince = Date.from(now.toInstant().minus(7, ChronoUnit.DAYS));
            return snapshot(
                    ACTIVE_LAST_7_DAYS,
                    "近 7 天有活跃记录的用户",
                    audienceMapper.countUsersActiveSince(activeSince),
                    now
            );
        }
        if (INACTIVE_30_DAYS.equals(segmentKey)) {
            Date inactiveBefore = Date.from(now.toInstant().minus(30, ChronoUnit.DAYS));
            return snapshot(
                    INACTIVE_30_DAYS,
                    "超过 30 天未登录的用户",
                    audienceMapper.countUsersInactiveBefore(inactiveBefore),
                    now
            );
        }
        return null;
    }

    public List<CampaignAudienceUser> listUsers(String segmentKey, Date now) {
        if (ALL_USERS.equals(segmentKey)) {
            return audienceMapper.selectAllUsers();
        }
        if (POINTS_AT_LEAST_500.equals(segmentKey)) {
            return audienceMapper.selectUsersWithMinimumPoints(MINIMUM_POINTS);
        }
        if (ACTIVE_LAST_7_DAYS.equals(segmentKey)) {
            return audienceMapper.selectUsersActiveSince(
                    Date.from(now.toInstant().minus(7, ChronoUnit.DAYS))
            );
        }
        if (INACTIVE_30_DAYS.equals(segmentKey)) {
            return audienceMapper.selectUsersInactiveBefore(
                    Date.from(now.toInstant().minus(30, ChronoUnit.DAYS))
            );
        }
        throw new IllegalArgumentException("不支持的活动客群: " + segmentKey);
    }

    public boolean isSupported(String segmentKey) {
        return ALL_USERS.equals(segmentKey)
                || POINTS_AT_LEAST_500.equals(segmentKey)
                || ACTIVE_LAST_7_DAYS.equals(segmentKey)
                || INACTIVE_30_DAYS.equals(segmentKey);
    }

    private CampaignSegmentSnapshotView snapshot(
            String key,
            String name,
            long users,
            Date now) {
        return new CampaignSegmentSnapshotView(key, name, users, now);
    }
}
