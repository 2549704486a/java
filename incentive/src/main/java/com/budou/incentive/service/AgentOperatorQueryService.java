package com.budou.incentive.service;

import com.budou.incentive.dao.mapper.AwardConfigMapper;
import com.budou.incentive.dao.mapper.AwardInventorySplitMapper;
import com.budou.incentive.dao.mapper.CampaignMetricHistoryMapper;
import com.budou.incentive.dao.mapper.TaskConfigMapper;
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

    public static final String ALL_USERS = CampaignAudienceService.ALL_USERS;
    public static final String POINTS_AT_LEAST_500 = CampaignAudienceService.POINTS_AT_LEAST_500;
    public static final String ACTIVE_LAST_7_DAYS = CampaignAudienceService.ACTIVE_LAST_7_DAYS;
    public static final String INACTIVE_30_DAYS = CampaignAudienceService.INACTIVE_30_DAYS;
    private static final String PARTICIPATION_RATE = "participation_rate";

    private final CampaignAudienceService audienceService;
    private final TaskConfigMapper taskConfigMapper;
    private final AwardConfigMapper awardConfigMapper;
    private final AwardInventorySplitMapper awardInventorySplitMapper;
    private final CampaignMetricHistoryMapper campaignMetricHistoryMapper;
    private final Supplier<Date> nowProvider;

    @Autowired
    public AgentOperatorQueryService(CampaignAudienceService audienceService,
                                     TaskConfigMapper taskConfigMapper,
                                     AwardConfigMapper awardConfigMapper,
                                     AwardInventorySplitMapper awardInventorySplitMapper,
                                     CampaignMetricHistoryMapper campaignMetricHistoryMapper) {
        this(audienceService, taskConfigMapper, awardConfigMapper,
                awardInventorySplitMapper, campaignMetricHistoryMapper, Date::new);
    }

    AgentOperatorQueryService(CampaignAudienceService audienceService,
                              TaskConfigMapper taskConfigMapper,
                              AwardConfigMapper awardConfigMapper,
                              AwardInventorySplitMapper awardInventorySplitMapper,
                              CampaignMetricHistoryMapper campaignMetricHistoryMapper,
                              Supplier<Date> nowProvider) {
        this.audienceService = audienceService;
        this.taskConfigMapper = taskConfigMapper;
        this.awardConfigMapper = awardConfigMapper;
        this.awardInventorySplitMapper = awardInventorySplitMapper;
        this.campaignMetricHistoryMapper = campaignMetricHistoryMapper;
        this.nowProvider = nowProvider;
    }

    public AgentToolResponse<CampaignPlanningSnapshotView> getPlanningSnapshot(String segmentKey) {
        Date now = nowProvider.get();
        CampaignSegmentSnapshotView segment = audienceService.getSegmentSnapshot(segmentKey, now);
        if (segment == null) {
            return AgentToolResponse.fail(
                    "UNSUPPORTED_CAMPAIGN_SEGMENT",
                    "不支持的客群标识，仅支持 ALL_USERS、POINTS_AT_LEAST_500、" +
                            "ACTIVE_LAST_7_DAYS 和 INACTIVE_30_DAYS",
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
