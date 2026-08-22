package com.budou.incentive.dto.agent;

import java.util.Date;

public record CampaignAwardSnapshotView(
        Long awardId,
        String awardName,
        Integer requiredPoints,
        long inventory,
        boolean active,
        Date availableFrom,
        Date availableUntil,
        String sourceRef
) {
}
