package com.budou.incentive.service;

import com.budou.incentive.dao.mapper.AwardConfigMapper;
import com.budou.incentive.dao.mapper.AwardInventorySplitMapper;
import com.budou.incentive.dao.mapper.CampaignMetricHistoryMapper;
import com.budou.incentive.dao.mapper.TaskConfigMapper;
import com.budou.incentive.dao.model.AwardConfig;
import com.budou.incentive.dao.model.CampaignMetricHistory;
import com.budou.incentive.dao.model.TaskConfig;
import com.budou.incentive.dto.agent.AgentToolResponse;
import com.budou.incentive.dto.agent.CampaignPlanningSnapshotView;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.math.BigDecimal;
import java.time.Instant;
import java.util.Date;
import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class AgentOperatorQueryServiceTest {

    private static final Date NOW = Date.from(Instant.parse("2026-08-22T04:00:00Z"));

    @Mock
    private CampaignAudienceService audienceService;
    @Mock
    private TaskConfigMapper taskConfigMapper;
    @Mock
    private AwardConfigMapper awardConfigMapper;
    @Mock
    private AwardInventorySplitMapper awardInventorySplitMapper;
    @Mock
    private CampaignMetricHistoryMapper campaignMetricHistoryMapper;

    private AgentOperatorQueryService service;

    @BeforeEach
    void setUp() {
        service = new AgentOperatorQueryService(
                audienceService,
                taskConfigMapper,
                awardConfigMapper,
                awardInventorySplitMapper,
                campaignMetricHistoryMapper,
                () -> NOW
        );
    }

    @Test
    void shouldBuildAllUsersSnapshotFromDatabaseFacts() {
        when(audienceService.getSegmentSnapshot(AgentOperatorQueryService.ALL_USERS, NOW))
                .thenReturn(new com.budou.incentive.dto.agent.CampaignSegmentSnapshotView(
                        AgentOperatorQueryService.ALL_USERS,
                        "全部积分用户",
                        20L,
                        NOW
                ));
        when(taskConfigMapper.selectAllTasks()).thenReturn(List.of(activeTask()));
        when(awardConfigMapper.selectAllAwards()).thenReturn(List.of(splitAward()));
        when(awardInventorySplitMapper.selectTotalInventory(6L)).thenReturn(19L);
        when(campaignMetricHistoryMapper.selectLatest(
                AgentOperatorQueryService.ALL_USERS,
                "participation_rate"
        )).thenReturn(metric(AgentOperatorQueryService.ALL_USERS));

        AgentToolResponse<CampaignPlanningSnapshotView> response = service.getPlanningSnapshot(
                AgentOperatorQueryService.ALL_USERS
        );

        assertTrue(response.success());
        assertEquals(20L, response.data().segment().estimatedUsers());
        assertEquals(19L, response.data().awards().get(0).inventory());
        assertEquals(19900, response.data().awards().get(0).unitCostCents());
        assertEquals(
                "award_config:6:unitCostCents",
                response.data().awards().get(0).costSourceRef()
        );
        assertEquals(
                "award_inventory_split:6:sum",
                response.data().awards().get(0).sourceRef()
        );
        assertEquals(1, response.data().historicalMetrics().size());
        assertEquals("task_config:1", response.data().tasks().get(0).sourceRef());
    }

    @Test
    void shouldUseFixedPointsThresholdForSupportedSegment() {
        when(audienceService.getSegmentSnapshot(
                AgentOperatorQueryService.POINTS_AT_LEAST_500,
                NOW
        )).thenReturn(new com.budou.incentive.dto.agent.CampaignSegmentSnapshotView(
                AgentOperatorQueryService.POINTS_AT_LEAST_500,
                "当前积分不少于 500 的用户",
                16L,
                NOW
        ));
        when(taskConfigMapper.selectAllTasks()).thenReturn(List.of());
        when(awardConfigMapper.selectAllAwards()).thenReturn(List.of());
        when(campaignMetricHistoryMapper.selectLatest(
                AgentOperatorQueryService.POINTS_AT_LEAST_500,
                "participation_rate"
        )).thenReturn(null);

        AgentToolResponse<CampaignPlanningSnapshotView> response = service.getPlanningSnapshot(
                AgentOperatorQueryService.POINTS_AT_LEAST_500
        );

        assertTrue(response.success());
        assertEquals(16L, response.data().segment().estimatedUsers());
        assertEquals(List.of(), response.data().historicalMetrics());
    }

    @Test
    void shouldRejectUnverifiableNaturalLanguageSegment() {
        when(audienceService.getSegmentSnapshot("最近30天未登录用户", NOW)).thenReturn(null);

        AgentToolResponse<CampaignPlanningSnapshotView> response = service.getPlanningSnapshot(
                "最近30天未登录用户"
        );

        assertFalse(response.success());
        assertEquals("UNSUPPORTED_CAMPAIGN_SEGMENT", response.code());
        verify(taskConfigMapper, never()).selectAllTasks();
    }

    private TaskConfig activeTask() {
        return new TaskConfig(
                1L,
                "每日签到",
                20,
                Date.from(NOW.toInstant().minusSeconds(3600)),
                Date.from(NOW.toInstant().plusSeconds(3600)),
                1,
                "完成签到"
        );
    }

    private AwardConfig splitAward() {
        return new AwardConfig(
                6L,
                "/watch.png",
                "智能手表",
                1,
                999,
                5000,
                19900,
                Date.from(NOW.toInstant().minusSeconds(3600)),
                Date.from(NOW.toInstant().plusSeconds(3600)),
                NOW,
                NOW,
                20,
                0
        );
    }

    private CampaignMetricHistory metric(String segmentKey) {
        return new CampaignMetricHistory(
                1L,
                segmentKey,
                "participation_rate",
                new BigDecimal("0.180000"),
                20,
                NOW,
                "demo_campaign_report:all_users"
        );
    }
}
