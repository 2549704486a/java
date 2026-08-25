package com.budou.incentive.service;

import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

@Slf4j
@Component
@ConditionalOnProperty(
        prefix = "campaign.metrics",
        name = "enabled",
        havingValue = "true",
        matchIfMissing = true
)
public class CampaignMetricsScheduler {

    private final CampaignEventProjector eventProjector;
    private final CampaignMetricsService metricsService;
    private final int activityLimit;

    public CampaignMetricsScheduler(
            CampaignEventProjector eventProjector,
            CampaignMetricsService metricsService,
            @Value("${campaign.metrics.activity-limit:50}") int activityLimit) {
        this.eventProjector = eventProjector;
        this.metricsService = metricsService;
        this.activityLimit = activityLimit;
    }

    @Scheduled(fixedDelayString = "${campaign.metrics.project-interval-ms:2000}")
    public void projectEvents() {
        try {
            int projected = eventProjector.projectAvailableFacts();
            if (projected > 0) {
                log.info("campaign events projected, count={}", projected);
            }
        } catch (RuntimeException exception) {
            log.error("campaign event projection failed", exception);
        }
    }

    @Scheduled(fixedDelayString = "${campaign.metrics.refresh-interval-ms:5000}")
    public void refreshMetrics() {
        try {
            metricsService.refreshRecent(activityLimit);
        } catch (RuntimeException exception) {
            log.error("campaign metric refresh failed", exception);
        }
    }
}
