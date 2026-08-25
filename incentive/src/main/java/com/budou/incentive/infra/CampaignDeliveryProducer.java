package com.budou.incentive.infra;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.apache.rocketmq.client.exception.MQClientException;
import org.apache.rocketmq.client.producer.DefaultMQProducer;
import org.apache.rocketmq.client.producer.SendResult;
import org.apache.rocketmq.common.message.Message;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Component;

import java.nio.charset.StandardCharsets;
import java.util.Map;

@Component
@ConditionalOnProperty(
        prefix = "campaign.delivery",
        name = "enabled",
        havingValue = "true",
        matchIfMissing = true
)
public class CampaignDeliveryProducer {

    private final DefaultMQProducer producer;
    private final ObjectMapper objectMapper;
    private final String topic;

    public CampaignDeliveryProducer(
            @Qualifier("campaignDeliveryMqProducer") DefaultMQProducer producer,
            ObjectMapper objectMapper,
            @Value("${campaign.delivery.topic:CampaignDeliveryTopic}") String topic) {
        this.producer = producer;
        this.objectMapper = objectMapper;
        this.topic = topic;
    }

    public SendResult sendInAppTask(Long deliveryTaskId)
            throws JsonProcessingException, MQClientException,
            org.apache.rocketmq.client.exception.MQBrokerException,
            InterruptedException, org.apache.rocketmq.remoting.exception.RemotingException {
        byte[] body = objectMapper.writeValueAsString(
                Map.of("deliveryTaskId", deliveryTaskId)
        ).getBytes(StandardCharsets.UTF_8);
        Message message = new Message(topic, "IN_APP", body);
        message.setKeys("campaign-delivery-task-" + deliveryTaskId);
        return producer.send(message, 3000);
    }
}
