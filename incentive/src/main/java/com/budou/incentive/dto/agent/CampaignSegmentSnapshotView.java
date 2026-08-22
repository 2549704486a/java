package com.budou.incentive.dto.agent;

import java.util.Date;

public record CampaignSegmentSnapshotView(
        String segmentKey,
        String description,
        long estimatedUsers,
        Date asOf
) {
}
