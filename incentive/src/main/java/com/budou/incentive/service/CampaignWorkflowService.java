package com.budou.incentive.service;

import com.budou.incentive.dao.mapper.CampaignActivityMapper;
import com.budou.incentive.dao.mapper.CampaignEffectMetricMapper;
import com.budou.incentive.dao.mapper.CampaignMetricHistoryMapper;
import com.budou.incentive.dao.mapper.CampaignPlanAuditMapper;
import com.budou.incentive.dao.mapper.CampaignPlanDraftMapper;
import com.budou.incentive.dao.model.CampaignActivity;
import com.budou.incentive.dao.model.CampaignEffectMetric;
import com.budou.incentive.dao.model.CampaignMetricHistory;
import com.budou.incentive.dao.model.CampaignPlanDraft;
import com.budou.incentive.dto.agent.AgentToolResponse;
import com.budou.incentive.dto.agent.CampaignActivityView;
import com.budou.incentive.dto.agent.CampaignDraftCreateCommand;
import com.budou.incentive.dto.agent.CampaignDraftView;
import com.budou.incentive.dto.agent.CampaignEffectMetricCommand;
import com.budou.incentive.dto.agent.CampaignEffectMetricView;
import com.budou.incentive.dto.agent.CampaignWorkflowActionCommand;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.math.BigDecimal;
import java.util.Date;
import java.util.List;
import java.util.function.Supplier;

@Service
public class CampaignWorkflowService {

    public static final String DRAFT = "DRAFT";
    public static final String PENDING_REVIEW = "PENDING_REVIEW";
    public static final String APPROVED = "APPROVED";
    public static final String REJECTED = "REJECTED";
    public static final String PUBLISHED = "PUBLISHED";

    private final CampaignPlanDraftMapper draftMapper;
    private final CampaignPlanAuditMapper auditMapper;
    private final CampaignActivityMapper activityMapper;
    private final CampaignEffectMetricMapper effectMetricMapper;
    private final CampaignMetricHistoryMapper metricHistoryMapper;
    private final Supplier<Date> nowProvider;

    @Autowired
    public CampaignWorkflowService(CampaignPlanDraftMapper draftMapper,
                                   CampaignPlanAuditMapper auditMapper,
                                   CampaignActivityMapper activityMapper,
                                   CampaignEffectMetricMapper effectMetricMapper,
                                   CampaignMetricHistoryMapper metricHistoryMapper) {
        this(draftMapper, auditMapper, activityMapper, effectMetricMapper,
                metricHistoryMapper, Date::new);
    }

    CampaignWorkflowService(CampaignPlanDraftMapper draftMapper,
                            CampaignPlanAuditMapper auditMapper,
                            CampaignActivityMapper activityMapper,
                            CampaignEffectMetricMapper effectMetricMapper,
                            CampaignMetricHistoryMapper metricHistoryMapper,
                            Supplier<Date> nowProvider) {
        this.draftMapper = draftMapper;
        this.auditMapper = auditMapper;
        this.activityMapper = activityMapper;
        this.effectMetricMapper = effectMetricMapper;
        this.metricHistoryMapper = metricHistoryMapper;
        this.nowProvider = nowProvider;
    }

    @Transactional
    public AgentToolResponse<CampaignDraftView> createDraft(CampaignDraftCreateCommand command) {
        String validationError = validateCreate(command);
        if (validationError != null) {
            return AgentToolResponse.fail("INVALID_CAMPAIGN_DRAFT", validationError, false);
        }
        CampaignPlanDraft existing = draftMapper.selectByDraftKey(command.draftKey());
        if (existing != null) {
            return AgentToolResponse.ok(
                    "CAMPAIGN_DRAFT_ALREADY_EXISTS",
                    toDraftView(existing),
                    "相同草案请求已经保存"
            );
        }

        Date now = nowProvider.get();
        CampaignPlanDraft draft = new CampaignPlanDraft();
        draft.setDraftKey(command.draftKey());
        draft.setVersion(1);
        draft.setOperatorId(command.operatorId());
        draft.setObjective(command.objective());
        draft.setTargetSegmentKey(command.targetSegmentKey());
        draft.setTargetSegment(command.targetSegment());
        draft.setBudgetAmountCents(command.budgetAmountCents());
        draft.setPointsIssuanceCap(command.pointsIssuanceCap());
        draft.setStartAt(command.startAt());
        draft.setEndAt(command.endAt());
        draft.setPlanJson(command.planJson());
        draft.setStatus(DRAFT);
        draft.setCreatedAt(now);
        draft.setUpdatedAt(now);
        draftMapper.insert(draft);
        auditMapper.insert(draft.getId(), "CREATE", null, DRAFT,
                command.operatorId(), "Agent 生成活动草案", now);
        return AgentToolResponse.ok(
                "CAMPAIGN_DRAFT_CREATED",
                toDraftView(draftMapper.selectById(draft.getId())),
                "活动草案已保存，等待提交审核"
        );
    }

    public AgentToolResponse<List<CampaignDraftView>> listDrafts(int limit) {
        int safeLimit = Math.max(1, Math.min(limit, 100));
        return AgentToolResponse.ok(
                "CAMPAIGN_DRAFTS_FOUND",
                draftMapper.selectRecent(safeLimit).stream().map(this::toDraftView).toList(),
                "活动草案读取成功"
        );
    }

    @Transactional
    public AgentToolResponse<CampaignDraftView> submitForReview(
            Long draftId,
            CampaignWorkflowActionCommand command) {
        CampaignPlanDraft draft = draftMapper.selectById(draftId);
        AgentToolResponse<CampaignDraftView> invalid = validateAction(draft, command, DRAFT);
        if (invalid != null) {
            return invalid;
        }
        Date now = nowProvider.get();
        if (draftMapper.submitForReview(draftId, command.version(), now) != 1) {
            return conflict(draftId);
        }
        auditMapper.insert(draftId, "SUBMIT_REVIEW", DRAFT, PENDING_REVIEW,
                command.operatorId(), command.comment(), now);
        return success("CAMPAIGN_DRAFT_SUBMITTED", draftId, "活动草案已提交人工审核");
    }

    @Transactional
    public AgentToolResponse<CampaignDraftView> approve(
            Long draftId,
            CampaignWorkflowActionCommand command) {
        return review(draftId, command, APPROVED, "APPROVE", "活动草案审核通过");
    }

    @Transactional
    public AgentToolResponse<CampaignDraftView> reject(
            Long draftId,
            CampaignWorkflowActionCommand command) {
        if (command == null || isBlank(command.comment())) {
            return AgentToolResponse.fail(
                    "REVIEW_COMMENT_REQUIRED",
                    "驳回草案时必须填写原因",
                    false
            );
        }
        return review(draftId, command, REJECTED, "REJECT", "活动草案已驳回");
    }

    @Transactional
    public AgentToolResponse<CampaignActivityView> publish(
            Long draftId,
            CampaignWorkflowActionCommand command) {
        CampaignPlanDraft draft = draftMapper.selectById(draftId);
        if (draft != null && PUBLISHED.equals(draft.getStatus())) {
            CampaignActivity existing = activityMapper.selectByDraftId(draftId);
            return AgentToolResponse.ok(
                    "CAMPAIGN_ALREADY_PUBLISHED",
                    toActivityView(existing),
                    "该草案已经发布"
            );
        }
        AgentToolResponse<CampaignDraftView> invalid = validateAction(draft, command, APPROVED);
        if (invalid != null) {
            return AgentToolResponse.fail(invalid.code(), invalid.message(), invalid.retryable());
        }
        Date now = nowProvider.get();
        if (!draft.getEndAt().after(now)) {
            return AgentToolResponse.fail(
                    "CAMPAIGN_WINDOW_EXPIRED",
                    "活动结束时间已经过去，不能发布",
                    false
            );
        }
        if (draftMapper.markPublished(draftId, command.version(), command.operatorId(), now) != 1) {
            return AgentToolResponse.fail(
                    "CAMPAIGN_DRAFT_VERSION_CONFLICT",
                    "草案状态或版本已经变化，请刷新后重试",
                    true
            );
        }

        CampaignActivity activity = new CampaignActivity();
        activity.setDraftId(draftId);
        activity.setObjective(draft.getObjective());
        activity.setTargetSegmentKey(draft.getTargetSegmentKey());
        activity.setBudgetAmountCents(draft.getBudgetAmountCents());
        activity.setPointsIssuanceCap(draft.getPointsIssuanceCap());
        activity.setStartAt(draft.getStartAt());
        activity.setEndAt(draft.getEndAt());
        activity.setPlanJson(draft.getPlanJson());
        activity.setStatus(draft.getStartAt().after(now) ? "SCHEDULED" : "ACTIVE");
        activity.setPublishedBy(command.operatorId());
        activity.setPublishedAt(now);
        activity.setCreatedAt(now);
        activity.setUpdatedAt(now);
        activityMapper.insert(activity);
        auditMapper.insert(draftId, "PUBLISH", APPROVED, PUBLISHED,
                command.operatorId(), command.comment(), now);
        return AgentToolResponse.ok(
                "CAMPAIGN_PUBLISHED",
                toActivityView(activity),
                "活动已通过确定性工作流发布"
        );
    }

    public AgentToolResponse<List<CampaignActivityView>> listActivities(int limit) {
        int safeLimit = Math.max(1, Math.min(limit, 100));
        return AgentToolResponse.ok(
                "CAMPAIGN_ACTIVITIES_FOUND",
                activityMapper.selectRecent(safeLimit).stream().map(this::toActivityView).toList(),
                "已发布活动读取成功"
        );
    }

    @Transactional
    public AgentToolResponse<CampaignEffectMetricView> recordMetric(
            Long activityId,
            CampaignEffectMetricCommand command) {
        CampaignActivity activity = activityMapper.selectById(activityId);
        if (activity == null) {
            return AgentToolResponse.fail("CAMPAIGN_ACTIVITY_NOT_FOUND", "活动不存在", false);
        }
        String validationError = validateMetric(command);
        if (validationError != null) {
            return AgentToolResponse.fail("INVALID_CAMPAIGN_METRIC", validationError, false);
        }
        Date now = nowProvider.get();
        Date measuredAt = command.measuredAt() == null ? now : command.measuredAt();
        CampaignEffectMetric metric = new CampaignEffectMetric();
        metric.setActivityId(activityId);
        metric.setMetricName(command.metricName());
        metric.setMetricValue(command.metricValue());
        metric.setSampleSize(command.sampleSize());
        metric.setMeasuredAt(measuredAt);
        metric.setSourceRef(command.sourceRef());
        metric.setRecordedBy(command.operatorId());
        metric.setCreatedAt(now);
        effectMetricMapper.insert(metric);

        // 同步写入规划快照使用的历史指标表，形成“发布 -> 观测 -> 下一轮规划”的反馈闭环。
        CampaignMetricHistory history = new CampaignMetricHistory(
                null,
                activity.getTargetSegmentKey(),
                command.metricName(),
                command.metricValue(),
                command.sampleSize(),
                measuredAt,
                command.sourceRef()
        );
        metricHistoryMapper.insert(history);
        return AgentToolResponse.ok(
                "CAMPAIGN_METRIC_RECORDED",
                toMetricView(metric),
                "活动效果指标已记录并回流规划历史"
        );
    }

    public AgentToolResponse<List<CampaignEffectMetricView>> listMetrics(Long activityId) {
        if (activityMapper.selectById(activityId) == null) {
            return AgentToolResponse.fail("CAMPAIGN_ACTIVITY_NOT_FOUND", "活动不存在", false);
        }
        return AgentToolResponse.ok(
                "CAMPAIGN_METRICS_FOUND",
                effectMetricMapper.selectByActivityId(activityId).stream()
                        .map(this::toMetricView)
                        .toList(),
                "活动效果指标读取成功"
        );
    }

    private AgentToolResponse<CampaignDraftView> review(
            Long draftId,
            CampaignWorkflowActionCommand command,
            String newStatus,
            String action,
            String message) {
        CampaignPlanDraft draft = draftMapper.selectById(draftId);
        AgentToolResponse<CampaignDraftView> invalid = validateAction(
                draft,
                command,
                PENDING_REVIEW
        );
        if (invalid != null) {
            return invalid;
        }
        Date now = nowProvider.get();
        if (draftMapper.review(draftId, command.version(), newStatus,
                command.operatorId(), command.comment(), now) != 1) {
            return conflict(draftId);
        }
        auditMapper.insert(draftId, action, PENDING_REVIEW, newStatus,
                command.operatorId(), command.comment(), now);
        return success("CAMPAIGN_DRAFT_" + newStatus, draftId, message);
    }

    private AgentToolResponse<CampaignDraftView> validateAction(
            CampaignPlanDraft draft,
            CampaignWorkflowActionCommand command,
            String expectedStatus) {
        if (draft == null) {
            return AgentToolResponse.fail("CAMPAIGN_DRAFT_NOT_FOUND", "活动草案不存在", false);
        }
        if (command == null || isBlank(command.operatorId()) || command.version() == null) {
            return AgentToolResponse.fail(
                    "INVALID_CAMPAIGN_ACTION",
                    "操作人和草案版本不能为空",
                    false
            );
        }
        if (!expectedStatus.equals(draft.getStatus())) {
            return AgentToolResponse.fail(
                    "INVALID_CAMPAIGN_DRAFT_STATUS",
                    "当前状态为 " + draft.getStatus() + "，不能执行该操作",
                    false
            );
        }
        if (!command.version().equals(draft.getVersion())) {
            return conflict(draft.getId());
        }
        return null;
    }

    private AgentToolResponse<CampaignDraftView> conflict(Long draftId) {
        CampaignPlanDraft current = draftMapper.selectById(draftId);
        return new AgentToolResponse<>(
                false,
                "CAMPAIGN_DRAFT_VERSION_CONFLICT",
                current == null ? null : toDraftView(current),
                "草案状态或版本已经变化，请刷新后重试",
                true
        );
    }

    private AgentToolResponse<CampaignDraftView> success(
            String code,
            Long draftId,
            String message) {
        return AgentToolResponse.ok(code, toDraftView(draftMapper.selectById(draftId)), message);
    }

    private String validateCreate(CampaignDraftCreateCommand command) {
        if (command == null || isBlank(command.draftKey()) || isBlank(command.operatorId())
                || isBlank(command.objective()) || isBlank(command.targetSegmentKey())
                || isBlank(command.targetSegment()) || isBlank(command.planJson())) {
            return "草案标识、操作人、目标、客群和方案不能为空";
        }
        if (command.budgetAmountCents() == null || command.budgetAmountCents() <= 0
                || command.pointsIssuanceCap() == null || command.pointsIssuanceCap() <= 0) {
            return "现金预算和积分发放上限必须大于 0";
        }
        if (command.startAt() == null || command.endAt() == null
                || !command.endAt().after(command.startAt())) {
            return "活动结束时间必须晚于开始时间";
        }
        return null;
    }

    private String validateMetric(CampaignEffectMetricCommand command) {
        if (command == null || isBlank(command.operatorId()) || isBlank(command.metricName())
                || command.metricValue() == null || command.sampleSize() == null
                || command.sampleSize() <= 0 || isBlank(command.sourceRef())) {
            return "指标名称、数值、样本量、来源和记录人不能为空";
        }
        if (command.metricValue().signum() < 0
                || command.metricValue().compareTo(BigDecimal.ONE) > 0) {
            return "比例类指标值必须在 0 到 1 之间";
        }
        return null;
    }

    private boolean isBlank(String value) {
        return value == null || value.isBlank();
    }

    private CampaignDraftView toDraftView(CampaignPlanDraft draft) {
        return new CampaignDraftView(
                draft.getId(), draft.getDraftKey(), draft.getVersion(), draft.getOperatorId(),
                draft.getObjective(), draft.getTargetSegmentKey(), draft.getTargetSegment(),
                draft.getBudgetAmountCents(), draft.getPointsIssuanceCap(), draft.getStartAt(),
                draft.getEndAt(), draft.getPlanJson(), draft.getStatus(), draft.getReviewerId(),
                draft.getReviewComment(), draft.getReviewedAt(), draft.getPublishedBy(),
                draft.getPublishedAt(), draft.getCreatedAt(), draft.getUpdatedAt()
        );
    }

    private CampaignActivityView toActivityView(CampaignActivity activity) {
        if (activity == null) {
            return null;
        }
        return new CampaignActivityView(
                activity.getId(), activity.getDraftId(), activity.getObjective(),
                activity.getTargetSegmentKey(), activity.getBudgetAmountCents(),
                activity.getPointsIssuanceCap(), activity.getStartAt(), activity.getEndAt(),
                activity.getPlanJson(), activity.getStatus(), activity.getPublishedBy(),
                activity.getPublishedAt(), activity.getCreatedAt(), activity.getUpdatedAt()
        );
    }

    private CampaignEffectMetricView toMetricView(CampaignEffectMetric metric) {
        return new CampaignEffectMetricView(
                metric.getId(), metric.getActivityId(), metric.getMetricName(),
                metric.getMetricValue(), metric.getSampleSize(), metric.getMeasuredAt(),
                metric.getSourceRef(), metric.getRecordedBy(), metric.getCreatedAt()
        );
    }
}
