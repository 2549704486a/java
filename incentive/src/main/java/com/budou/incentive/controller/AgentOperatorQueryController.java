package com.budou.incentive.controller;

import com.budou.incentive.dto.agent.AgentToolResponse;
import com.budou.incentive.dto.agent.CampaignPlanningSnapshotView;
import com.budou.incentive.service.AgentOperatorQueryService;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("agent/operator/query")
public class AgentOperatorQueryController {

    private final AgentOperatorQueryService agentOperatorQueryService;

    public AgentOperatorQueryController(AgentOperatorQueryService agentOperatorQueryService) {
        this.agentOperatorQueryService = agentOperatorQueryService;
    }

    @GetMapping("campaign-planning/snapshots/{segmentKey}")
    public AgentToolResponse<CampaignPlanningSnapshotView> getCampaignPlanningSnapshot(
            @PathVariable String segmentKey) {
        return agentOperatorQueryService.getPlanningSnapshot(segmentKey);
    }
}
