package com.budou.incentive.service;

import com.budou.incentive.dao.mapper.CampaignEventMapper;
import com.budou.incentive.dao.model.CampaignEvent;
import com.budou.incentive.dao.model.CampaignEventCandidate;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

import java.util.Date;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.function.IntFunction;

@Slf4j
@Service
public class CampaignEventProjector {

    private final CampaignEventMapper eventMapper;
    private final ObjectMapper objectMapper;
    private final int batchSize;

    public CampaignEventProjector(
            CampaignEventMapper eventMapper,
            ObjectMapper objectMapper,
            @Value("${campaign.metrics.project-batch-size:200}") int batchSize) {
        this.eventMapper = eventMapper;
        this.objectMapper = objectMapper;
        this.batchSize = batchSize;
    }

    public int projectAvailableFacts() {
        int projected = 0;
        projected += project("notification:delivered:", "DELIVERED", "notification_id",
                eventMapper::selectUnprojectedDelivered);
        projected += project("notification:view:", "VIEW", "notification_id",
                eventMapper::selectUnprojectedViews);
        projected += project("notification:click:", "CLICK", "notification_id",
                eventMapper::selectUnprojectedClicks);
        projected += projectActivityScoped("task:complete:", "TASK_COMPLETE", "task_record_id",
                eventMapper::selectUnprojectedTaskCompletions);
        projected += projectActivityScoped("exchange:success:", "EXCHANGE", "user_award_id",
                eventMapper::selectUnprojectedExchanges);
        return projected;
    }

    int project(String keyPrefix,
                String eventType,
                String metadataField,
                IntFunction<List<CampaignEventCandidate>> candidateLoader) {
        return projectCandidates(keyPrefix, eventType, metadataField,
                candidateLoader.apply(batchSize), false);
    }

    int projectActivityScoped(String keyPrefix,
                              String eventType,
                              String metadataField,
                              IntFunction<List<CampaignEventCandidate>> candidateLoader) {
        return projectCandidates(keyPrefix, eventType, metadataField,
                candidateLoader.apply(batchSize), true);
    }

    private int projectCandidates(String keyPrefix,
                                  String eventType,
                                  String metadataField,
                                  List<CampaignEventCandidate> candidates,
                                  boolean activityScopedKey) {
        int inserted = 0;
        for (CampaignEventCandidate candidate : candidates) {
            CampaignEvent event = new CampaignEvent();
            event.setEventKey(activityScopedKey
                    ? keyPrefix + candidate.getActivityId() + ":" + candidate.getReferenceId()
                    : keyPrefix + candidate.getReferenceId());
            event.setActivityId(candidate.getActivityId());
            event.setUserId(candidate.getUserId());
            event.setEventType(eventType);
            event.setSource(candidate.getSource());
            event.setOccurredAt(candidate.getOccurredAt());
            event.setMetadataJson(metadata(metadataField, candidate.getReferenceId()));
            event.setCreatedAt(new Date());
            inserted += eventMapper.insertIfAbsent(event);
        }
        return inserted;
    }

    private String metadata(String field, Long referenceId) {
        Map<String, Object> metadata = new LinkedHashMap<>();
        metadata.put(field, referenceId);
        try {
            return objectMapper.writeValueAsString(metadata);
        } catch (JsonProcessingException exception) {
            log.warn("campaign event metadata serialization failed, field={}, referenceId={}",
                    field, referenceId, exception);
            return null;
        }
    }
}
