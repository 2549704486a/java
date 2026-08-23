package com.budou.incentive.dto.agent;

public record CampaignWorkflowActionCommand(
        String operatorId,
        Integer version,
        String comment
) {
}
