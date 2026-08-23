package com.budou.incentive.service;

import com.budou.incentive.dao.mapper.CampaignActivityMapper;
import com.budou.incentive.dao.mapper.CampaignEffectMetricMapper;
import com.budou.incentive.dao.mapper.CampaignMetricHistoryMapper;
import com.budou.incentive.dao.mapper.CampaignPlanAuditMapper;
import com.budou.incentive.dao.mapper.CampaignPlanDraftMapper;
import com.budou.incentive.dao.model.CampaignActivity;
import com.budou.incentive.dao.model.CampaignPlanDraft;
import com.budou.incentive.dto.agent.AgentToolResponse;
import com.budou.incentive.dto.agent.CampaignActivityView;
import com.budou.incentive.dto.agent.CampaignDraftCreateCommand;
import com.budou.incentive.dto.agent.CampaignDraftView;
import com.budou.incentive.dto.agent.CampaignEffectMetricCommand;
import com.budou.incentive.dto.agent.CampaignEffectMetricView;
import com.budou.incentive.dto.agent.CampaignWorkflowActionCommand;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.math.BigDecimal;
import java.util.Date;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class CampaignWorkflowServiceTest {

    private static final Date NOW = new Date(1_787_500_000_000L);
    private static final Date START = new Date(NOW.getTime() + 86_400_000L);
    private static final Date END = new Date(NOW.getTime() + 7 * 86_400_000L);

    @Mock
    private CampaignPlanDraftMapper draftMapper;
    @Mock
    private CampaignPlanAuditMapper auditMapper;
    @Mock
    private CampaignActivityMapper activityMapper;
    @Mock
    private CampaignEffectMetricMapper effectMetricMapper;
    @Mock
    private CampaignMetricHistoryMapper metricHistoryMapper;

    private CampaignWorkflowService service;

    @BeforeEach
    void setUp() {
        service = new CampaignWorkflowService(
                draftMapper,
                auditMapper,
                activityMapper,
                effectMetricMapper,
                metricHistoryMapper,
                () -> NOW
        );
    }

    @Test
    void createsPersistentDraftAndAuditRecord() {
        when(draftMapper.selectByDraftKey("draft-key-1")).thenReturn(null);
        when(draftMapper.insert(any())).thenAnswer(invocation -> {
            CampaignPlanDraft draft = invocation.getArgument(0);
            draft.setId(11L);
            return 1;
        });
        when(draftMapper.selectById(11L)).thenAnswer(invocation -> {
            CampaignPlanDraft draft = baseDraft(CampaignWorkflowService.DRAFT, 1);
            draft.setId(11L);
            return draft;
        });

        AgentToolResponse<CampaignDraftView> response = service.createDraft(
                new CampaignDraftCreateCommand(
                        "draft-key-1",
                        "operator-01",
                        "提升任务参与率",
                        "POINTS_AT_LEAST_500",
                        "积分不少于500的用户",
                        100_000L,
                        5_000L,
                        START,
                        END,
                        "{\"status\":\"draft\"}"
                )
        );

        assertTrue(response.success());
        assertEquals("CAMPAIGN_DRAFT_CREATED", response.code());
        verify(auditMapper).insert(
                eq(11L), eq("CREATE"), eq(null), eq("DRAFT"),
                eq("operator-01"), any(), eq(NOW)
        );
    }

    @Test
    void rejectsStaleWorkflowVersion() {
        CampaignPlanDraft draft = baseDraft(CampaignWorkflowService.DRAFT, 3);
        draft.setId(11L);
        when(draftMapper.selectById(11L)).thenReturn(draft);

        AgentToolResponse<CampaignDraftView> response = service.submitForReview(
                11L,
                new CampaignWorkflowActionCommand("operator-01", 2, "提交审核")
        );

        assertFalse(response.success());
        assertEquals("CAMPAIGN_DRAFT_VERSION_CONFLICT", response.code());
        assertEquals(3, response.data().version());
    }

    @Test
    void publishesOnlyApprovedDraftThroughDeterministicWorkflow() {
        CampaignPlanDraft approved = baseDraft(CampaignWorkflowService.APPROVED, 3);
        approved.setId(11L);
        when(draftMapper.selectById(11L)).thenReturn(approved);
        when(draftMapper.markPublished(11L, 3, "publisher-01", NOW)).thenReturn(1);
        when(activityMapper.insert(any())).thenAnswer(invocation -> {
            CampaignActivity activity = invocation.getArgument(0);
            activity.setId(21L);
            return 1;
        });

        AgentToolResponse<CampaignActivityView> response = service.publish(
                11L,
                new CampaignWorkflowActionCommand("publisher-01", 3, "审核已完成")
        );

        assertTrue(response.success());
        assertEquals("CAMPAIGN_PUBLISHED", response.code());
        assertEquals(21L, response.data().id());
        assertEquals("SCHEDULED", response.data().status());
        verify(auditMapper).insert(
                11L, "PUBLISH", "APPROVED", "PUBLISHED",
                "publisher-01", "审核已完成", NOW
        );
    }

    @Test
    void recordsEffectMetricAndFeedsPlanningHistory() {
        CampaignActivity activity = new CampaignActivity();
        activity.setId(21L);
        activity.setTargetSegmentKey("POINTS_AT_LEAST_500");
        when(activityMapper.selectById(21L)).thenReturn(activity);
        when(effectMetricMapper.insert(any())).thenAnswer(invocation -> {
            invocation.<com.budou.incentive.dao.model.CampaignEffectMetric>getArgument(0)
                    .setId(31L);
            return 1;
        });

        AgentToolResponse<CampaignEffectMetricView> response = service.recordMetric(
                21L,
                new CampaignEffectMetricCommand(
                        "analyst-01",
                        "participation_rate",
                        new BigDecimal("0.320000"),
                        500,
                        NOW,
                        "campaign_activity:21:report"
                )
        );

        assertTrue(response.success());
        assertEquals("CAMPAIGN_METRIC_RECORDED", response.code());
        verify(effectMetricMapper).insert(any());
        verify(metricHistoryMapper).insert(any());
    }

    private CampaignPlanDraft baseDraft(String status, int version) {
        CampaignPlanDraft draft = new CampaignPlanDraft();
        draft.setId(11L);
        draft.setDraftKey("draft-key-1");
        draft.setVersion(version);
        draft.setOperatorId("operator-01");
        draft.setObjective("提升任务参与率");
        draft.setTargetSegmentKey("POINTS_AT_LEAST_500");
        draft.setTargetSegment("积分不少于500的用户");
        draft.setBudgetAmountCents(100_000L);
        draft.setPointsIssuanceCap(5_000L);
        draft.setStartAt(START);
        draft.setEndAt(END);
        draft.setPlanJson("{\"status\":\"draft\"}");
        draft.setStatus(status);
        draft.setCreatedAt(NOW);
        draft.setUpdatedAt(NOW);
        return draft;
    }
}
