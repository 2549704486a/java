package com.budou.incentive.service;

import com.budou.incentive.dao.mapper.CampaignEventMapper;
import com.budou.incentive.dao.model.CampaignEvent;
import com.budou.incentive.dao.model.CampaignEventCandidate;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.time.Instant;
import java.util.Date;
import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class CampaignEventProjectorTest {

    @Mock
    private CampaignEventMapper eventMapper;

    @Test
    void shouldProjectNotificationFactWithStableEventKey() {
        CampaignEventCandidate candidate = candidate(7L, 10L, 31L);
        when(eventMapper.insertIfAbsent(any())).thenReturn(1);
        CampaignEventProjector projector = new CampaignEventProjector(
                eventMapper,
                new ObjectMapper(),
                100
        );

        int inserted = projector.project(
                "notification:delivered:",
                "DELIVERED",
                "notification_id",
                ignored -> List.of(candidate)
        );

        ArgumentCaptor<CampaignEvent> captor = ArgumentCaptor.forClass(CampaignEvent.class);
        verify(eventMapper).insertIfAbsent(captor.capture());
        CampaignEvent event = captor.getValue();
        assertEquals(1, inserted);
        assertEquals("notification:delivered:31", event.getEventKey());
        assertEquals("DELIVERED", event.getEventType());
        assertEquals("SIMULATED", event.getSource());
        assertTrue(event.getMetadataJson().contains("\"notification_id\":31"));
    }

    @Test
    void shouldScopeTaskFactByActivity() {
        CampaignEventCandidate candidate = candidate(7L, 10L, 42L);
        when(eventMapper.insertIfAbsent(any())).thenReturn(1);
        CampaignEventProjector projector = new CampaignEventProjector(
                eventMapper,
                new ObjectMapper(),
                100
        );

        projector.projectActivityScoped(
                "task:complete:",
                "TASK_COMPLETE",
                "task_record_id",
                ignored -> List.of(candidate)
        );

        ArgumentCaptor<CampaignEvent> captor = ArgumentCaptor.forClass(CampaignEvent.class);
        verify(eventMapper).insertIfAbsent(captor.capture());
        assertEquals("task:complete:7:42", captor.getValue().getEventKey());
    }

    private CampaignEventCandidate candidate(Long activityId, Long userId, Long referenceId) {
        CampaignEventCandidate candidate = new CampaignEventCandidate();
        candidate.setActivityId(activityId);
        candidate.setUserId(userId);
        candidate.setReferenceId(referenceId);
        candidate.setOccurredAt(Date.from(Instant.parse("2026-08-25T08:00:00Z")));
        candidate.setSource("SIMULATED");
        return candidate;
    }
}
