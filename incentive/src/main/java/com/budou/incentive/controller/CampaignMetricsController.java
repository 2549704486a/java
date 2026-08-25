package com.budou.incentive.controller;

import com.budou.incentive.dto.agent.AgentToolResponse;
import com.budou.incentive.dto.agent.CampaignFunnelView;
import com.budou.incentive.service.CampaignMetricsService;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("agent/operator/campaigns")
public class CampaignMetricsController {

    private final CampaignMetricsService metricsService;

    public CampaignMetricsController(CampaignMetricsService metricsService) {
        this.metricsService = metricsService;
    }

    @GetMapping("activities/{activityId}/funnel")
    public AgentToolResponse<CampaignFunnelView> getFunnel(@PathVariable Long activityId) {
        return metricsService.getFunnel(activityId);
    }
}
