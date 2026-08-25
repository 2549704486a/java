package com.budou.incentive.service;

import com.budou.incentive.dao.model.CampaignActivity;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

@Slf4j
@Component
@ConditionalOnProperty(
        prefix = "campaign.execution",
        name = "enabled",
        havingValue = "true",
        matchIfMissing = true
)
public class CampaignExecutionScheduler {

    private final CampaignExecutionService executionService;
    private final int scanLimit;

    public CampaignExecutionScheduler(
            CampaignExecutionService executionService,
            @Value("${campaign.execution.scan-limit:20}") int scanLimit) {
        this.executionService = executionService;
        this.scanLimit = scanLimit;
    }

    @Scheduled(fixedDelayString = "${campaign.execution.scan-interval-ms:5000}")
    public void scanDueActivities() {
        for (CampaignActivity activity : executionService.findDueActivities(scanLimit)) {
            try {
                executionService.startActivity(activity.getId());
            } catch (RuntimeException exception) {
                // 单个活动失败不能阻断同批次其他活动，下一轮扫描仍可重试未建执行实例的活动。
                log.error("campaign execution start failed, activityId={}",
                        activity.getId(), exception);
            }
        }
    }
}
