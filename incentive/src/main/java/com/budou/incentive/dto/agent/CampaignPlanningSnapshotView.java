package com.budou.incentive.dto.agent;

import java.util.Date;
import java.util.List;

public record CampaignPlanningSnapshotView(
        String snapshotId,
        Date generatedAt,
        CampaignSegmentSnapshotView segment,
        List<CampaignTaskSnapshotView> tasks,
        List<CampaignAwardSnapshotView> awards,
        List<HistoricalCampaignMetricView> historicalMetrics
) {
}
