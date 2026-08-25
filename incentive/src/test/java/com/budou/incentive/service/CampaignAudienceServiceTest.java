package com.budou.incentive.service;

import com.budou.incentive.dao.mapper.CampaignAudienceMapper;
import com.budou.incentive.dto.agent.CampaignSegmentSnapshotView;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.Date;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class CampaignAudienceServiceTest {

    private static final Date NOW = Date.from(Instant.parse("2026-08-25T08:00:00Z"));

    @Mock
    private CampaignAudienceMapper audienceMapper;

    @Test
    void shouldUseSameActiveWindowForPlanningAndExecution() {
        CampaignAudienceService service = new CampaignAudienceService(audienceMapper);
        Date expectedSince = Date.from(NOW.toInstant().minus(7, ChronoUnit.DAYS));
        when(audienceMapper.countUsersActiveSince(expectedSince)).thenReturn(8L);

        CampaignSegmentSnapshotView snapshot = service.getSegmentSnapshot(
                CampaignAudienceService.ACTIVE_LAST_7_DAYS,
                NOW
        );
        service.listUsers(CampaignAudienceService.ACTIVE_LAST_7_DAYS, NOW);

        assertEquals(8L, snapshot.estimatedUsers());
        ArgumentCaptor<Date> captor = ArgumentCaptor.forClass(Date.class);
        verify(audienceMapper).selectUsersActiveSince(captor.capture());
        assertEquals(expectedSince, captor.getValue());
    }

    @Test
    void shouldNotGuessUnsupportedNaturalLanguageSegment() {
        CampaignAudienceService service = new CampaignAudienceService(audienceMapper);

        assertNull(service.getSegmentSnapshot("最近经常来的用户", NOW));
    }
}
