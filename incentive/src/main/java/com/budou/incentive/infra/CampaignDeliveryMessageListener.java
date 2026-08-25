package com.budou.incentive.infra;

import com.budou.incentive.service.CampaignDeliveryService;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.extern.slf4j.Slf4j;
import org.apache.rocketmq.client.consumer.listener.ConsumeConcurrentlyContext;
import org.apache.rocketmq.client.consumer.listener.ConsumeConcurrentlyStatus;
import org.apache.rocketmq.client.consumer.listener.MessageListenerConcurrently;
import org.apache.rocketmq.common.message.MessageExt;
import org.springframework.stereotype.Component;

import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.Map;

@Slf4j
@Component
public class CampaignDeliveryMessageListener implements MessageListenerConcurrently {

    private final ObjectMapper objectMapper;
    private final CampaignDeliveryService deliveryService;

    public CampaignDeliveryMessageListener(
            ObjectMapper objectMapper,
            CampaignDeliveryService deliveryService) {
        this.objectMapper = objectMapper;
        this.deliveryService = deliveryService;
    }

    @Override
    public ConsumeConcurrentlyStatus consumeMessage(
            List<MessageExt> messages,
            ConsumeConcurrentlyContext context) {
        for (MessageExt message : messages) {
            Long taskId;
            try {
                Map<?, ?> payload = objectMapper.readValue(
                        new String(message.getBody(), StandardCharsets.UTF_8),
                        Map.class
                );
                taskId = Long.valueOf(String.valueOf(payload.get("deliveryTaskId")));
            } catch (Exception exception) {
                // 无法识别的消息无法通过重试修复，记录后确认，避免成为永久毒消息。
                log.error("invalid campaign delivery message, msgId={}",
                        message.getMsgId(), exception);
                continue;
            }

            try {
                deliveryService.consumeInAppTask(taskId);
            } catch (RuntimeException exception) {
                log.error("campaign delivery consume failed, taskId={}, msgId={}",
                        taskId, message.getMsgId(), exception);
                return ConsumeConcurrentlyStatus.RECONSUME_LATER;
            }
        }
        return ConsumeConcurrentlyStatus.CONSUME_SUCCESS;
    }
}
