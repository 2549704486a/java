package com.budou.incentive.controller;

import com.budou.incentive.dto.agent.AgentToolResponse;
import com.budou.incentive.dto.agent.CampaignSimulationCommand;
import com.budou.incentive.dto.agent.CampaignSimulationView;
import com.budou.incentive.service.CampaignSimulationService;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("agent/operator/campaigns")
public class CampaignSimulationController {

    private final CampaignSimulationService simulationService;

    public CampaignSimulationController(CampaignSimulationService simulationService) {
        this.simulationService = simulationService;
    }

    @PostMapping("activities/{activityId}/simulate")
    public AgentToolResponse<CampaignSimulationView> simulate(
            @PathVariable Long activityId,
            @RequestBody CampaignSimulationCommand command) {
        return simulationService.simulate(activityId, command);
    }
}
