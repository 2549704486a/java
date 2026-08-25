package com.budou.incentive.infra;

import jakarta.annotation.Resource;
import org.apache.rocketmq.client.consumer.DefaultMQPushConsumer;
import org.apache.rocketmq.client.producer.DefaultMQProducer;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
@ConditionalOnProperty(
        prefix = "campaign.delivery",
        name = "enabled",
        havingValue = "true",
        matchIfMissing = true
)
public class CampaignDeliveryMqConfig {

    @Value("${rocketmq.name-server}")
    private String nameServer;
    @Value("${campaign.delivery.producer-group:campaign_delivery_producer}")
    private String producerGroup;
    @Value("${campaign.delivery.consumer-group:campaign_delivery_consumer}")
    private String consumerGroup;
    @Value("${campaign.delivery.topic:CampaignDeliveryTopic}")
    private String topic;

    @Resource
    private CampaignDeliveryMessageListener messageListener;

    @Bean(name = "campaignDeliveryMqProducer", initMethod = "start", destroyMethod = "shutdown")
    public DefaultMQProducer campaignDeliveryMqProducer() {
        DefaultMQProducer producer = new DefaultMQProducer(producerGroup);
        producer.setNamesrvAddr(nameServer);
        producer.setRetryTimesWhenSendFailed(2);
        return producer;
    }

    @Bean(name = "campaignDeliveryMqConsumer", initMethod = "start", destroyMethod = "shutdown")
    public DefaultMQPushConsumer campaignDeliveryMqConsumer() throws Exception {
        DefaultMQPushConsumer consumer = new DefaultMQPushConsumer(consumerGroup);
        consumer.setNamesrvAddr(nameServer);
        consumer.subscribe(topic, "IN_APP");
        consumer.setConsumeMessageBatchMaxSize(1);
        consumer.setMaxReconsumeTimes(5);
        consumer.registerMessageListener(messageListener);
        return consumer;
    }
}
