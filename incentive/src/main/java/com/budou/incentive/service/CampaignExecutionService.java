package com.budou.incentive.service;

import com.budou.incentive.dao.mapper.CampaignActivityMapper;
import com.budou.incentive.dao.mapper.CampaignDeliveryTaskMapper;
import com.budou.incentive.dao.mapper.CampaignExecutionMapper;
import com.budou.incentive.dao.mapper.CampaignTargetUserMapper;
import com.budou.incentive.dao.model.CampaignActivity;
import com.budou.incentive.dao.model.CampaignAudienceUser;
import com.budou.incentive.dao.model.CampaignDeliveryTask;
import com.budou.incentive.dao.model.CampaignExecution;
import com.budou.incentive.dao.model.CampaignTargetUser;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.temporal.ChronoUnit;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Date;
import java.util.HashSet;
import java.util.List;
import java.util.Random;
import java.util.Set;
import java.util.function.Supplier;

/**
 * 将已发布活动转换为固定客群快照、实验分组和可靠投放任务。
 */
@Service
public class CampaignExecutionService {

    public static final String PENDING = "PENDING";
    public static final String RUNNING = "RUNNING";
    public static final String COMPLETED = "COMPLETED";
    public static final String TREATMENT = "TREATMENT";
    public static final String CONTROL = "CONTROL";
    public static final String IN_APP = "IN_APP";
    public static final String DEMO_PUSH = "DEMO_PUSH";
    public static final String NONE = "NONE";

    private static final int BASIS_POINTS = 10_000;

    private final CampaignActivityMapper activityMapper;
    private final CampaignExecutionMapper executionMapper;
    private final CampaignTargetUserMapper targetUserMapper;
    private final CampaignDeliveryTaskMapper deliveryTaskMapper;
    private final CampaignAudienceService audienceService;
    private final int treatmentRatioBps;
    private final Supplier<Date> nowProvider;

    @Autowired
    public CampaignExecutionService(
            CampaignActivityMapper activityMapper,
            CampaignExecutionMapper executionMapper,
            CampaignTargetUserMapper targetUserMapper,
            CampaignDeliveryTaskMapper deliveryTaskMapper,
            CampaignAudienceService audienceService,
            @Value("${campaign.execution.treatment-ratio-bps:9000}") int treatmentRatioBps) {
        this(activityMapper, executionMapper, targetUserMapper, deliveryTaskMapper,
                audienceService, treatmentRatioBps, Date::new);
    }

    CampaignExecutionService(
            CampaignActivityMapper activityMapper,
            CampaignExecutionMapper executionMapper,
            CampaignTargetUserMapper targetUserMapper,
            CampaignDeliveryTaskMapper deliveryTaskMapper,
            CampaignAudienceService audienceService,
            int treatmentRatioBps,
            Supplier<Date> nowProvider) {
        if (treatmentRatioBps < 0 || treatmentRatioBps > BASIS_POINTS) {
            throw new IllegalArgumentException("实验组占比必须在 0 到 10000 之间");
        }
        this.activityMapper = activityMapper;
        this.executionMapper = executionMapper;
        this.targetUserMapper = targetUserMapper;
        this.deliveryTaskMapper = deliveryTaskMapper;
        this.audienceService = audienceService;
        this.treatmentRatioBps = treatmentRatioBps;
        this.nowProvider = nowProvider;
    }

    public List<CampaignActivity> findDueActivities(int limit) {
        int safeLimit = Math.max(1, Math.min(limit, 100));
        return activityMapper.selectDueWithoutExecution(nowProvider.get(), safeLimit);
    }

    @Transactional
    public CampaignExecution startActivity(Long activityId) {
        CampaignExecution existing = executionMapper.selectByActivityId(activityId);
        if (existing != null) {
            return existing;
        }

        Date now = nowProvider.get();
        CampaignActivity activity = activityMapper.selectById(activityId);
        validateExecutable(activity, now);

        CampaignExecution execution = new CampaignExecution();
        execution.setActivityId(activityId);
        execution.setStatus(PENDING);
        execution.setTreatmentRatioBps(treatmentRatioBps);
        execution.setCreatedAt(now);
        execution.setUpdatedAt(now);
        if (executionMapper.insertIfAbsent(execution) != 1) {
            return executionMapper.selectByActivityId(activityId);
        }

        List<CampaignAudienceUser> candidates = audienceService.listUsers(
                activity.getTargetSegmentKey(),
                now
        );
        List<CampaignTargetUser> targets = buildTargets(activity, execution, candidates, now);
        if (targets.isEmpty()) {
            executionMapper.markEmptyCompleted(execution.getId(), now);
            execution.setStatus(COMPLETED);
            execution.setTotalUsers(0);
            execution.setTreatmentUsers(0);
            execution.setControlUsers(0);
            execution.setStartedAt(now);
            execution.setCompletedAt(now);
            return currentExecution(execution);
        }

        targetUserMapper.insertBatch(targets);
        List<CampaignTargetUser> persistedTargets = targetUserMapper.selectByExecutionId(
                execution.getId()
        );
        if (persistedTargets.size() != targets.size()) {
            throw new IllegalStateException("活动目标用户快照写入不完整");
        }

        List<CampaignDeliveryTask> tasks = buildDeliveryTasks(persistedTargets, now);
        if (!tasks.isEmpty()) {
            deliveryTaskMapper.insertBatch(tasks);
        }

        int treatmentUsers = (int) persistedTargets.stream()
                .filter(target -> TREATMENT.equals(target.getExperimentGroup()))
                .count();
        int controlUsers = persistedTargets.size() - treatmentUsers;
        executionMapper.markRunning(
                execution.getId(),
                persistedTargets.size(),
                treatmentUsers,
                controlUsers,
                now,
                now
        );
        activityMapper.markActive(activityId, now);

        execution.setStatus(RUNNING);
        execution.setTotalUsers(persistedTargets.size());
        execution.setTreatmentUsers(treatmentUsers);
        execution.setControlUsers(controlUsers);
        execution.setStartedAt(now);
        return currentExecution(execution);
    }

    private List<CampaignTargetUser> buildTargets(
            CampaignActivity activity,
            CampaignExecution execution,
            List<CampaignAudienceUser> candidates,
            Date now) {
        List<CampaignAudienceUser> ordered = new ArrayList<>(candidates);
        ordered.sort((left, right) -> left.getUserId().compareTo(right.getUserId()));

        List<CampaignAudienceUser> shuffled = new ArrayList<>(ordered);
        Collections.shuffle(shuffled, new Random(activity.getId()));
        int treatmentCount = calculateTreatmentCount(shuffled.size());
        Set<Long> treatmentUserIds = new HashSet<>();
        for (int index = 0; index < treatmentCount; index++) {
            treatmentUserIds.add(shuffled.get(index).getUserId());
        }

        List<CampaignTargetUser> targets = new ArrayList<>(ordered.size());
        for (CampaignAudienceUser candidate : ordered) {
            boolean treatment = treatmentUserIds.contains(candidate.getUserId());
            CampaignTargetUser target = new CampaignTargetUser();
            target.setExecutionId(execution.getId());
            target.setActivityId(activity.getId());
            target.setUserId(candidate.getUserId());
            target.setExperimentGroup(treatment ? TREATMENT : CONTROL);
            target.setDeliveryChannel(treatment ? resolveChannel(candidate, now) : NONE);
            target.setPointsSnapshot(candidate.getPoints() == null ? 0L : candidate.getPoints());
            target.setLastActiveAtSnapshot(candidate.getLastActiveAt());
            target.setDataSource(
                    candidate.getDataSource() == null ? "REAL" : candidate.getDataSource()
            );
            target.setAssignedAt(now);
            targets.add(target);
        }
        return targets;
    }

    private List<CampaignDeliveryTask> buildDeliveryTasks(
            List<CampaignTargetUser> targets,
            Date now) {
        List<CampaignDeliveryTask> tasks = new ArrayList<>();
        for (CampaignTargetUser target : targets) {
            if (!TREATMENT.equals(target.getExperimentGroup())
                    || NONE.equals(target.getDeliveryChannel())) {
                continue;
            }
            CampaignDeliveryTask task = new CampaignDeliveryTask();
            task.setExecutionId(target.getExecutionId());
            task.setActivityId(target.getActivityId());
            task.setTargetUserId(target.getId());
            task.setUserId(target.getUserId());
            task.setChannel(target.getDeliveryChannel());
            task.setStatus(PENDING);
            task.setAttemptCount(0);
            task.setMaxAttempts(3);
            task.setNextAttemptAt(now);
            task.setCreatedAt(now);
            task.setUpdatedAt(now);
            tasks.add(task);
        }
        return tasks;
    }

    private int calculateTreatmentCount(int totalUsers) {
        int count = (int) Math.round(totalUsers * (treatmentRatioBps / (double) BASIS_POINTS));
        if (totalUsers > 1 && treatmentRatioBps > 0 && count == 0) {
            return 1;
        }
        if (totalUsers > 1 && treatmentRatioBps < BASIS_POINTS && count == totalUsers) {
            return totalUsers - 1;
        }
        return count;
    }

    private String resolveChannel(CampaignAudienceUser candidate, Date now) {
        Date inactiveBefore = Date.from(now.toInstant().minus(30, ChronoUnit.DAYS));
        if (candidate.getLastActiveAt() != null
                && candidate.getLastActiveAt().before(inactiveBefore)) {
            return DEMO_PUSH;
        }
        return IN_APP;
    }

    private void validateExecutable(CampaignActivity activity, Date now) {
        if (activity == null) {
            throw new IllegalArgumentException("活动不存在");
        }
        if (!audienceService.isSupported(activity.getTargetSegmentKey())) {
            throw new IllegalArgumentException(
                    "活动使用了不支持的客群: " + activity.getTargetSegmentKey()
            );
        }
        if (activity.getStartAt() == null || activity.getEndAt() == null
                || now.before(activity.getStartAt()) || !now.before(activity.getEndAt())) {
            throw new IllegalStateException("活动不在可执行时间窗口内");
        }
        if (!("SCHEDULED".equals(activity.getStatus())
                || "ACTIVE".equals(activity.getStatus()))) {
            throw new IllegalStateException("活动状态不可执行: " + activity.getStatus());
        }
    }

    private CampaignExecution currentExecution(CampaignExecution fallback) {
        CampaignExecution current = executionMapper.selectById(fallback.getId());
        return current == null ? fallback : current;
    }
}
