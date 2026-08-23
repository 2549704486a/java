package com.budou.incentive.controller;

import com.budou.incentive.dto.agent.AgentToolResponse;
import com.budou.incentive.dto.agent.CampaignActivityView;
import com.budou.incentive.dto.agent.CampaignDraftCreateCommand;
import com.budou.incentive.dto.agent.CampaignDraftView;
import com.budou.incentive.dto.agent.CampaignEffectMetricCommand;
import com.budou.incentive.dto.agent.CampaignEffectMetricView;
import com.budou.incentive.dto.agent.CampaignWorkflowActionCommand;
import com.budou.incentive.service.CampaignWorkflowService;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

@RestController
@RequestMapping("agent/operator/campaigns")
public class CampaignWorkflowController {

    private final CampaignWorkflowService workflowService;

    public CampaignWorkflowController(CampaignWorkflowService workflowService) {
        this.workflowService = workflowService;
    }

    @PostMapping("drafts")
    public AgentToolResponse<CampaignDraftView> createDraft(
            @RequestBody CampaignDraftCreateCommand command) {
        return workflowService.createDraft(command);
    }

    @GetMapping("drafts")
    public AgentToolResponse<List<CampaignDraftView>> listDrafts(
            @RequestParam(defaultValue = "50") int limit) {
        return workflowService.listDrafts(limit);
    }

    @PostMapping("drafts/{draftId}/submit")
    public AgentToolResponse<CampaignDraftView> submitForReview(
            @PathVariable Long draftId,
            @RequestBody CampaignWorkflowActionCommand command) {
        return workflowService.submitForReview(draftId, command);
    }

    @PostMapping("drafts/{draftId}/approve")
    public AgentToolResponse<CampaignDraftView> approve(
            @PathVariable Long draftId,
            @RequestBody CampaignWorkflowActionCommand command) {
        return workflowService.approve(draftId, command);
    }

    @PostMapping("drafts/{draftId}/reject")
    public AgentToolResponse<CampaignDraftView> reject(
            @PathVariable Long draftId,
            @RequestBody CampaignWorkflowActionCommand command) {
        return workflowService.reject(draftId, command);
    }

    @PostMapping("drafts/{draftId}/publish")
    public AgentToolResponse<CampaignActivityView> publish(
            @PathVariable Long draftId,
            @RequestBody CampaignWorkflowActionCommand command) {
        return workflowService.publish(draftId, command);
    }

    @GetMapping("activities")
    public AgentToolResponse<List<CampaignActivityView>> listActivities(
            @RequestParam(defaultValue = "50") int limit) {
        return workflowService.listActivities(limit);
    }

    @PostMapping("activities/{activityId}/metrics")
    public AgentToolResponse<CampaignEffectMetricView> recordMetric(
            @PathVariable Long activityId,
            @RequestBody CampaignEffectMetricCommand command) {
        return workflowService.recordMetric(activityId, command);
    }

    @GetMapping("activities/{activityId}/metrics")
    public AgentToolResponse<List<CampaignEffectMetricView>> listMetrics(
            @PathVariable Long activityId) {
        return workflowService.listMetrics(activityId);
    }
}
