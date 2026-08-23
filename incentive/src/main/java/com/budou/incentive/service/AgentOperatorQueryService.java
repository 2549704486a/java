package com.budou.incentive.service;

import com.budou.incentive.dao.mapper.AwardConfigMapper;
import com.budou.incentive.dao.mapper.AwardInventorySplitMapper;
import com.budou.incentive.dao.mapper.CampaignMetricHistoryMapper;
import com.budou.incentive.dao.mapper.TaskConfigMapper;
import com.budou.incentive.dao.mapper.UserCurrencyMapper;
import com.budou.incentive.dao.model.AwardConfig;
import com.budou.incentive.dao.model.CampaignMetricHistory;
import com.budou.incentive.dao.model.TaskConfig;
import com.budou.incentive.dto.agent.AgentToolResponse;
import com.budou.incentive.dto.agent.CampaignAwardSnapshotView;
import com.budou.incentive.dto.agent.CampaignPlanningSnapshotView;
import com.budou.incentive.dto.agent.CampaignSegmentSnapshotView;
import com.budou.incentive.dto.agent.CampaignTaskSnapshotView;
import com.budou.incentive.dto.agent.HistoricalCampaignMetricView;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

import java.util.Date;
import java.util.List;
import java.util.UUID;
import java.util.function.Supplier;

@Service
public class AgentOperatorQueryService {

    public static final String ALL_USERS = "ALL_USERS";
    public static final String POINTS_AT_LEAST_500 = "POINTS_AT_LEAST_500";
    private static final String PARTICIPATION_RATE = "participation_rate";

    private final UserCurrencyMapper userCurrencyMapper;
    private final TaskConfigMapper taskConfigMapper;
    private final AwardConfigMapper awardConfigMapper;
    private final AwardInventorySplitMapper awardInventorySplitMapper;
    private final CampaignMetricHistoryMapper campaignMetricHistoryMapper;
    private final Supplier<Date> nowProvider;

    @Autowired
    public AgentOperatorQueryService(UserCurrencyMapper userCurrencyMapper,
                                     TaskConfigMapper taskConfigMapper,
                                     AwardConfigMapper awardConfigMapper,
                                     AwardInventorySplitMapper awardInventorySplitMapper,
                                     CampaignMetricHistoryMapper campaignMetricHistoryMapper) {
        this(userCurrencyMapper, taskConfigMapper, awardConfigMapper,
                awardInventorySplitMapper, campaignMetricHistoryMapper, Date::new);
    }

    AgentOperatorQueryService(UserCurrencyMapper userCurrencyMapper,
                              TaskConfigMapper taskConfigMapper,
                              AwardConfigMapper awardConfigMapper,
                              AwardInventorySplitMapper awardInventorySplitMapper,
                              CampaignMetricHistoryMapper campaignMetricHistoryMapper,
                              Supplier<Date> nowProvider) {
        this.userCurrencyMapper = userCurrencyMapper;
        this.taskConfigMapper = taskConfigMapper;
        this.awardConfigMapper = awardConfigMapper;
        this.awardInventorySplitMapper = awardInventorySplitMapper;
        this.campaignMetricHistoryMapper = campaignMetricHistoryMapper;
        this.nowProvider = nowProvider;
    }

    public AgentToolResponse<CampaignPlanningSnapshotView> getPlanningSnapshot(String segmentKey) {
        Date now = nowProvider.get();
        CampaignSegmentSnapshotView segment = resolveSegment(segmentKey, now);
        if (segment == null) {
            return AgentToolResponse.fail(
                    "UNSUPPORTED_CAMPAIGN_SEGMENT",
                    "不支持的客群标识，仅支持 ALL_USERS 和 POINTS_AT_LEAST_500",
                    false
            );
        }

        List<CampaignTaskSnapshotView> tasks = taskConfigMapper.selectAllTasks().stream()
                .map(task -> toTaskSnapshot(task, now))
                .toList();
        List<CampaignAwardSnapshotView> awards = awardConfigMapper.selectAllAwards().stream()
                .map(award -> toAwardSnapshot(award, now))
                .toList();

        CampaignMetricHistory history = campaignMetricHistoryMapper.selectLatest(
                segmentKey,
                PARTICIPATION_RATE
        );
        List<HistoricalCampaignMetricView> metrics = history == null
                ? List.of()
                : List.of(new HistoricalCampaignMetricView(
                        history.getMetricName(),
                        history.getMetricValue(),
                        history.getSampleSize(),
                        history.getMeasuredAt(),
                        history.getSourceRef()
                ));

        CampaignPlanningSnapshotView snapshot = new CampaignPlanningSnapshotView(
                UUID.randomUUID().toString(),
                now,
                segment,
                tasks,
                awards,
                metrics
        );
        return AgentToolResponse.ok(
                "CAMPAIGN_SNAPSHOT_FOUND",
                snapshot,
                "运营活动规划快照读取成功"
        );
    }

    private CampaignSegmentSnapshotView resolveSegment(String segmentKey, Date now) {
        if (ALL_USERS.equals(segmentKey)) {
            return new CampaignSegmentSnapshotView(
                    ALL_USERS,
                    "全部积分用户",
                    userCurrencyMapper.countAllUsers(),
                    now
            );
        }
        if (POINTS_AT_LEAST_500.equals(segmentKey)) {
            return new CampaignSegmentSnapshotView(
                    POINTS_AT_LEAST_500,
                    "当前积分不少于 500 的用户",
                    userCurrencyMapper.countUsersWithMinimumPoints(500),
                    now
            );
        }
        return null;
    }

    private CampaignTaskSnapshotView toTaskSnapshot(TaskConfig task, Date now) {
        return new CampaignTaskSnapshotView(
                task.getTaskId(),
                task.getTaskName(),
                task.getCurrency(),
                1,
                isAvailable(task.getStartTime(), task.getEndTime(), now),
                task.getStartTime(),
                task.getEndTime(),
                "task_config:" + task.getTaskId()
        );
    }

    private CampaignAwardSnapshotView toAwardSnapshot(AwardConfig award, Date now) {
        long inventory = Integer.valueOf(1).equals(award.getIsOverSell())
                ? award.getInventory()
                : awardInventorySplitMapper.selectTotalInventory(award.getAwardId());
        return new CampaignAwardSnapshotView(
                award.getAwardId(),
                award.getName(),
                award.getPrice(),
                award.getUnitCostCents(),
                inventory,
                inventory > 0 && isAvailable(award.getStartTime(), award.getEndTime(), now),
                award.getStartTime(),
                award.getEndTime(),
                "award_config:" + award.getAwardId() + ":unitCostCents",
                Integer.valueOf(1).equals(award.getIsOverSell())
                        ? "award_config:" + award.getAwardId() + ":inventory"
                        : "award_inventory_split:" + award.getAwardId() + ":sum"
        );
    }

    private boolean isAvailable(Date startTime, Date endTime, Date now) {
        return (startTime == null || !now.before(startTime))
                && (endTime == null || !now.after(endTime));
    }
}
