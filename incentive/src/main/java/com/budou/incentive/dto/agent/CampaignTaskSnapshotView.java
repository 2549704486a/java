package com.budou.incentive.dto.agent;

import java.util.Date;

public record CampaignTaskSnapshotView(
        Long taskId,
        String taskName,
        Integer rewardPoints,
        Integer maxCompletionsPerUser,
        boolean active,
        Date availableFrom,
        Date availableUntil,
        String sourceRef
) {
}
