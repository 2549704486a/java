package com.budou.incentive.service;

import com.budou.incentive.dao.mapper.CampaignDeliveryTaskMapper;
import com.budou.incentive.dao.model.CampaignDeliveryTask;
import com.budou.incentive.infra.CampaignDeliveryProducer;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import java.time.temporal.ChronoUnit;
import java.util.Date;

@Slf4j
@Component
@ConditionalOnProperty(
        prefix = "campaign.delivery",
        name = "enabled",
        havingValue = "true",
        matchIfMissing = true
)
public class CampaignDeliveryDispatcher {

    private final CampaignDeliveryTaskMapper taskMapper;
    private final CampaignDeliveryProducer producer;
    private final int dispatchLimit;

    public CampaignDeliveryDispatcher(
            CampaignDeliveryTaskMapper taskMapper,
            CampaignDeliveryProducer producer,
            @Value("${campaign.delivery.dispatch-limit:100}") int dispatchLimit) {
        this.taskMapper = taskMapper;
        this.producer = producer;
        this.dispatchLimit = dispatchLimit;
    }

    @Scheduled(fixedDelayString = "${campaign.delivery.dispatch-interval-ms:1000}")
    public void dispatchInAppTasks() {
        Date now = new Date();
        taskMapper.recoverStaleProcessing(
                CampaignExecutionService.IN_APP,
                Date.from(now.toInstant().minus(60, ChronoUnit.SECONDS)),
                now
        );
        int safeLimit = Math.max(1, Math.min(dispatchLimit, 500));
        for (Long taskId : taskMapper.selectDispatchableIds(
                CampaignExecutionService.IN_APP,
                now,
                safeLimit)) {
            if (taskMapper.claim(taskId, now) != 1) {
                continue;
            }
            CampaignDeliveryTask task = taskMapper.selectById(taskId);
            try {
                producer.sendInAppTask(taskId);
                log.info("campaign delivery task dispatched, taskId={}, attempt={}",
                        taskId, task == null ? null : task.getAttemptCount());
            } catch (Exception exception) {
                if (exception instanceof InterruptedException) {
                    Thread.currentThread().interrupt();
                }
                Date failedAt = new Date();
                Date nextAttempt = Date.from(failedAt.toInstant().plus(5, ChronoUnit.SECONDS));
                taskMapper.markDispatchFailure(
                        taskId,
                        nextAttempt,
                        abbreviate(exception.getClass().getSimpleName() + ": " + exception.getMessage()),
                        failedAt
                );
                log.error("campaign delivery dispatch failed, taskId={}, attempt={}",
                        taskId, task == null ? null : task.getAttemptCount(), exception);
            }
        }
    }

    private String abbreviate(String message) {
        if (message == null) {
            return "unknown-dispatch-error";
        }
        return message.length() <= 500 ? message : message.substring(0, 500);
    }
}
