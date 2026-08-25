package com.budou.incentive.service;

import com.budou.incentive.dao.mapper.CampaignEventMapper;
import com.budou.incentive.dao.mapper.CampaignExecutionMapper;
import com.budou.incentive.dao.mapper.CampaignTargetUserMapper;
import com.budou.incentive.dao.model.CampaignEvent;
import com.budou.incentive.dao.model.CampaignExecution;
import com.budou.incentive.dao.model.CampaignTargetUser;
import com.budou.incentive.dto.agent.AgentToolResponse;
import com.budou.incentive.dto.agent.CampaignFunnelView;
import com.budou.incentive.dto.agent.CampaignSimulationCommand;
import com.budou.incentive.dto.agent.CampaignSimulationView;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

import java.util.Date;
import java.util.List;
import java.util.function.Supplier;

@Service
public class CampaignSimulationService {

    public static final String DEMO_BASELINE_V1 = "DEMO_BASELINE_V1";
    private static final String TREATMENT = "TREATMENT";
    private static final String CONTROL = "CONTROL";
    private static final String SIMULATED = "SIMULATED";
    private static final String METADATA =
            "{\"scenario\":\"DEMO_BASELINE_V1\",\"mode\":\"DETERMINISTIC_FIXTURE\"}";

    private final CampaignExecutionMapper executionMapper;
    private final CampaignTargetUserMapper targetUserMapper;
    private final CampaignEventMapper eventMapper;
    private final CampaignMetricsService metricsService;
    private final Supplier<Date> nowProvider;

    @Autowired
    public CampaignSimulationService(CampaignExecutionMapper executionMapper,
                                     CampaignTargetUserMapper targetUserMapper,
                                     CampaignEventMapper eventMapper,
                                     CampaignMetricsService metricsService) {
        this(executionMapper, targetUserMapper, eventMapper, metricsService, Date::new);
    }

    CampaignSimulationService(CampaignExecutionMapper executionMapper,
                              CampaignTargetUserMapper targetUserMapper,
                              CampaignEventMapper eventMapper,
                              CampaignMetricsService metricsService,
                              Supplier<Date> nowProvider) {
        this.executionMapper = executionMapper;
        this.targetUserMapper = targetUserMapper;
        this.eventMapper = eventMapper;
        this.metricsService = metricsService;
        this.nowProvider = nowProvider;
    }

    public AgentToolResponse<CampaignSimulationView> simulate(
            Long activityId,
            CampaignSimulationCommand command) {
        if (command == null || !DEMO_BASELINE_V1.equals(command.scenarioKey())) {
            return AgentToolResponse.fail(
                    "INVALID_CAMPAIGN_SIMULATION",
                    "只支持固定演示场景 " + DEMO_BASELINE_V1,
                    false
            );
        }

        CampaignExecution execution = executionMapper.selectByActivityId(activityId);
        if (execution == null) {
            return AgentToolResponse.fail(
                    "CAMPAIGN_EXECUTION_NOT_FOUND",
                    "活动尚未生成执行实例，不能生成演示行为",
                    false
            );
        }

        List<CampaignTargetUser> targets = targetUserMapper.selectByExecutionId(execution.getId());
        if (targets.isEmpty()) {
            return AgentToolResponse.fail(
                    "CAMPAIGN_SIMULATION_TARGETS_EMPTY",
                    "活动没有目标用户，不能生成演示行为",
                    false
            );
        }
        if (targets.stream().anyMatch(target -> !"FIXTURE".equals(target.getDataSource()))) {
            return AgentToolResponse.fail(
                    "CAMPAIGN_SIMULATION_REQUIRES_FIXTURE",
                    "演示行为只能作用于完全由 Fixture 构成的活动",
                    false
            );
        }

        List<CampaignTargetUser> treatment = targets.stream()
                .filter(target -> TREATMENT.equals(target.getExperimentGroup()))
                .toList();
        List<CampaignTargetUser> control = targets.stream()
                .filter(target -> CONTROL.equals(target.getExperimentGroup()))
                .toList();
        Date occurredAt = nowProvider.get();
        int inserted = 0;

        // Stable ordering keeps smaller cohorts reproducible and nested within larger cohorts.
        inserted += emit(treatment, "DELIVERED", treatment.size(), occurredAt);
        inserted += emit(treatment, "VIEW", ceilRatio(treatment.size(), 7000), occurredAt);
        inserted += emit(treatment, "CLICK", ceilRatio(treatment.size(), 4500), occurredAt);
        inserted += emit(treatment, "TASK_COMPLETE", ceilRatio(treatment.size(), 5500), occurredAt);
        inserted += emit(treatment, "EXCHANGE", ceilRatio(treatment.size(), 2500), occurredAt);
        inserted += emit(control, "TASK_COMPLETE", floorRatio(control.size(), 2000), occurredAt);
        inserted += emit(control, "EXCHANGE", floorRatio(control.size(), 800), occurredAt);

        CampaignFunnelView funnel = metricsService.refreshAndGet(activityId);
        String code = inserted > 0
                ? "CAMPAIGN_SIMULATION_APPLIED"
                : "CAMPAIGN_SIMULATION_ALREADY_APPLIED";
        String message = inserted > 0
                ? "演示行为已生成，活动漏斗已刷新"
                : "固定演示行为已经存在，活动漏斗保持不变";
        return AgentToolResponse.ok(
                code,
                new CampaignSimulationView(
                        activityId,
                        DEMO_BASELINE_V1,
                        inserted,
                        SIMULATED,
                        funnel
                ),
                message
        );
    }

    private int emit(List<CampaignTargetUser> targets,
                     String eventType,
                     int count,
                     Date occurredAt) {
        int inserted = 0;
        int boundedCount = Math.min(count, targets.size());
        for (int index = 0; index < boundedCount; index++) {
            CampaignTargetUser target = targets.get(index);
            CampaignEvent event = new CampaignEvent();
            event.setEventKey("simulation:" + DEMO_BASELINE_V1 + ":" +
                    target.getActivityId() + ":" + target.getUserId() + ":" + eventType);
            event.setActivityId(target.getActivityId());
            event.setUserId(target.getUserId());
            event.setEventType(eventType);
            event.setSource(SIMULATED);
            event.setOccurredAt(occurredAt);
            event.setMetadataJson(METADATA);
            event.setCreatedAt(occurredAt);
            inserted += eventMapper.insertIfAbsent(event);
        }
        return inserted;
    }

    private static int ceilRatio(int total, int basisPoints) {
        return (int) (((long) total * basisPoints + 9999) / 10000);
    }

    private static int floorRatio(int total, int basisPoints) {
        return (int) ((long) total * basisPoints / 10000);
    }
}
