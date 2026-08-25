package com.budou.incentive.service;

import com.budou.incentive.dao.mapper.CampaignEffectMetricMapper;
import com.budou.incentive.dao.mapper.CampaignEventMapper;
import com.budou.incentive.dao.mapper.CampaignExecutionMapper;
import com.budou.incentive.dao.mapper.CampaignTargetUserMapper;
import com.budou.incentive.dao.model.CampaignEffectMetric;
import com.budou.incentive.dao.model.CampaignEventCount;
import com.budou.incentive.dao.model.CampaignExecution;
import com.budou.incentive.dto.agent.AgentToolResponse;
import com.budou.incentive.dto.agent.CampaignFunnelView;
import com.budou.incentive.dto.agent.CampaignGroupFunnelView;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.util.Date;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.function.Supplier;

@Service
public class CampaignMetricsService {

    private static final String TREATMENT = "TREATMENT";
    private static final String CONTROL = "CONTROL";

    private final CampaignExecutionMapper executionMapper;
    private final CampaignTargetUserMapper targetUserMapper;
    private final CampaignEventMapper eventMapper;
    private final CampaignEffectMetricMapper effectMetricMapper;
    private final Supplier<Date> nowProvider;

    @Autowired
    public CampaignMetricsService(CampaignExecutionMapper executionMapper,
                                  CampaignTargetUserMapper targetUserMapper,
                                  CampaignEventMapper eventMapper,
                                  CampaignEffectMetricMapper effectMetricMapper) {
        this(executionMapper, targetUserMapper, eventMapper, effectMetricMapper, Date::new);
    }

    CampaignMetricsService(CampaignExecutionMapper executionMapper,
                           CampaignTargetUserMapper targetUserMapper,
                           CampaignEventMapper eventMapper,
                           CampaignEffectMetricMapper effectMetricMapper,
                           Supplier<Date> nowProvider) {
        this.executionMapper = executionMapper;
        this.targetUserMapper = targetUserMapper;
        this.eventMapper = eventMapper;
        this.effectMetricMapper = effectMetricMapper;
        this.nowProvider = nowProvider;
    }

    public AgentToolResponse<CampaignFunnelView> getFunnel(Long activityId) {
        CampaignFunnelView funnel = calculate(activityId, false);
        if (funnel == null) {
            return AgentToolResponse.fail(
                    "CAMPAIGN_EXECUTION_NOT_FOUND",
                    "活动尚未生成执行实例，暂时没有可计算的效果数据",
                    false
            );
        }
        return AgentToolResponse.ok(
                "CAMPAIGN_FUNNEL_FOUND",
                funnel,
                "活动实验漏斗读取成功"
        );
    }

    public CampaignFunnelView refreshAndGet(Long activityId) {
        return calculate(activityId, true);
    }

    private CampaignFunnelView calculate(Long activityId, boolean persistSnapshot) {
        CampaignExecution execution = executionMapper.selectByActivityId(activityId);
        if (execution == null) {
            return null;
        }

        Map<String, Integer> eventUsers = new HashMap<>();
        for (CampaignEventCount count : eventMapper
                .countDistinctUsersByGroupAndType(activityId)) {
            eventUsers.put(key(count.getExperimentGroup(), count.getEventType()),
                    count.getEventUsers());
        }

        Date measuredAt = nowProvider.get();
        CampaignGroupFunnelView treatment = groupView(
                TREATMENT,
                safe(execution.getTreatmentUsers()),
                eventUsers
        );
        CampaignGroupFunnelView control = groupView(
                CONTROL,
                safe(execution.getControlUsers()),
                eventUsers
        );
        BigDecimal taskLift = treatment.taskCompletionRate()
                .subtract(control.taskCompletionRate());
        BigDecimal exchangeLift = treatment.exchangeRate()
                .subtract(control.exchangeRate());
        String dataSource = dataSource(
                safe(execution.getTotalUsers()),
                targetUserMapper.countNonRealByActivityId(activityId)
        );

        if (persistSnapshot) {
            persist(execution, treatment, control, taskLift, exchangeLift, measuredAt);
        }
        return new CampaignFunnelView(
                activityId,
                execution.getId(),
                dataSource,
                treatment,
                control,
                taskLift,
                exchangeLift,
                measuredAt
        );
    }

    public void refreshRecent(int limit) {
        for (Long activityId : executionMapper.selectRecentActivityIds(limit)) {
            refreshAndGet(activityId);
        }
    }

    private CampaignGroupFunnelView groupView(String group,
                                               int targeted,
                                               Map<String, Integer> eventUsers) {
        int delivered = eventUsers.getOrDefault(key(group, "DELIVERED"), 0);
        int viewed = eventUsers.getOrDefault(key(group, "VIEW"), 0);
        int clicked = eventUsers.getOrDefault(key(group, "CLICK"), 0);
        int taskCompleted = eventUsers.getOrDefault(key(group, "TASK_COMPLETE"), 0);
        int exchanged = eventUsers.getOrDefault(key(group, "EXCHANGE"), 0);
        return new CampaignGroupFunnelView(
                group,
                targeted,
                delivered,
                viewed,
                clicked,
                taskCompleted,
                exchanged,
                rate(delivered, targeted),
                rate(viewed, delivered),
                rate(clicked, delivered),
                rate(taskCompleted, targeted),
                rate(exchanged, targeted)
        );
    }

    private void persist(CampaignExecution execution,
                         CampaignGroupFunnelView treatment,
                         CampaignGroupFunnelView control,
                         BigDecimal taskLift,
                         BigDecimal exchangeLift,
                         Date measuredAt) {
        String sourceRef = "AUTO_EXECUTION:" + execution.getId();
        upsert(execution.getActivityId(), "TREATMENT_DELIVERY_RATE",
                treatment.deliveryRate(), treatment.targetedUsers(), measuredAt, sourceRef);
        upsert(execution.getActivityId(), "TREATMENT_VIEW_RATE",
                treatment.viewRate(), treatment.deliveredUsers(), measuredAt, sourceRef);
        upsert(execution.getActivityId(), "TREATMENT_CLICK_RATE",
                treatment.clickRate(), treatment.deliveredUsers(), measuredAt, sourceRef);
        upsert(execution.getActivityId(), "TREATMENT_TASK_COMPLETION_RATE",
                treatment.taskCompletionRate(), treatment.targetedUsers(), measuredAt, sourceRef);
        upsert(execution.getActivityId(), "CONTROL_TASK_COMPLETION_RATE",
                control.taskCompletionRate(), control.targetedUsers(), measuredAt, sourceRef);
        upsert(execution.getActivityId(), "TREATMENT_EXCHANGE_RATE",
                treatment.exchangeRate(), treatment.targetedUsers(), measuredAt, sourceRef);
        upsert(execution.getActivityId(), "CONTROL_EXCHANGE_RATE",
                control.exchangeRate(), control.targetedUsers(), measuredAt, sourceRef);
        upsert(execution.getActivityId(), "TASK_COMPLETION_LIFT",
                taskLift, safe(execution.getTotalUsers()), measuredAt, sourceRef);
        upsert(execution.getActivityId(), "EXCHANGE_LIFT",
                exchangeLift, safe(execution.getTotalUsers()), measuredAt, sourceRef);
    }

    private void upsert(Long activityId,
                        String metricName,
                        BigDecimal metricValue,
                        int sampleSize,
                        Date measuredAt,
                        String sourceRef) {
        CampaignEffectMetric metric = new CampaignEffectMetric();
        metric.setActivityId(activityId);
        metric.setMetricName(metricName);
        metric.setMetricValue(metricValue);
        metric.setSampleSize(sampleSize);
        metric.setMeasuredAt(measuredAt);
        metric.setSourceRef(sourceRef);
        metric.setRecordedBy("SYSTEM");
        metric.setCreatedAt(measuredAt);
        effectMetricMapper.upsert(metric);
    }

    private static BigDecimal rate(int numerator, int denominator) {
        if (denominator <= 0) {
            return BigDecimal.ZERO.setScale(6, RoundingMode.HALF_UP);
        }
        return BigDecimal.valueOf(numerator)
                .divide(BigDecimal.valueOf(denominator), 6, RoundingMode.HALF_UP);
    }

    private static int safe(Integer value) {
        return value == null ? 0 : value;
    }

    private static String dataSource(int totalUsers, int nonRealUsers) {
        if (nonRealUsers <= 0) {
            return "REAL";
        }
        if (nonRealUsers >= totalUsers) {
            return "SIMULATED";
        }
        return "MIXED";
    }

    private static String key(String group, String eventType) {
        return group + ":" + eventType;
    }
}
