package com.budou.incentive.controller;

import com.budou.incentive.dto.agent.AgentToolResponse;
import com.budou.incentive.dto.agent.AwardDetailView;
import com.budou.incentive.dto.agent.AwardOptionView;
import com.budou.incentive.dto.agent.ExchangeEligibilityView;
import com.budou.incentive.dto.agent.TaskOptionView;
import com.budou.incentive.dto.agent.UserPointsView;
import com.budou.incentive.service.AgentQueryService;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

@RestController
@RequestMapping("agent/query")
public class AgentQueryController {

    private final AgentQueryService agentQueryService;

    public AgentQueryController(AgentQueryService agentQueryService) {
        this.agentQueryService = agentQueryService;
    }

    @GetMapping("users/{userId}/points")
    public AgentToolResponse<UserPointsView> getUserPoints(@PathVariable Long userId) {
        return agentQueryService.getUserPoints(userId);
    }

    @GetMapping("users/{userId}/tasks")
    public AgentToolResponse<List<TaskOptionView>> listAvailableTasks(@PathVariable Long userId) {
        return agentQueryService.listAvailableTasks(userId);
    }

    @GetMapping("awards/{awardId}")
    public AgentToolResponse<AwardDetailView> getAwardDetail(@PathVariable Long awardId) {
        return agentQueryService.getAwardDetail(awardId);
    }

    @GetMapping("users/{userId}/awards")
    public AgentToolResponse<List<AwardOptionView>> listAwards(
            @PathVariable Long userId,
            @RequestParam(defaultValue = "false") boolean redeemableOnly) {
        return agentQueryService.listAwards(userId, redeemableOnly);
    }

    @GetMapping("users/{userId}/awards/{awardId}/eligibility")
    public AgentToolResponse<ExchangeEligibilityView> checkExchangeEligibility(
            @PathVariable Long userId,
            @PathVariable Long awardId) {
        return agentQueryService.checkExchangeEligibility(userId, awardId);
    }
}

