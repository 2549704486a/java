package com.budou.incentive.dto.agent;

public record CampaignSimulationView(
        Long activityId,
        String scenarioKey,
        int insertedEvents,
        String dataSource,
        CampaignFunnelView funnel
) {
}
