package com.budou.incentive.infra;

import com.budou.incentive.utils.Result;
import com.budou.incentive.utils.ResultCodeEnum;
import lombok.extern.slf4j.Slf4j;
import org.apache.rocketmq.client.producer.SendStatus;
import org.apache.rocketmq.client.producer.TransactionSendResult;
import org.apache.rocketmq.spring.core.RocketMQTemplate;
import org.apache.rocketmq.spring.support.RocketMQHeaders;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.messaging.Message;
import org.springframework.messaging.support.MessageBuilder;
import org.springframework.stereotype.Service;

@Service
@Slf4j
public class TransactionProducer {
    @Autowired
    private RocketMQTemplate rocketMQTemplate;

    @Value("${rocketmq.topic}")
    private String topic;

    public Result sendTransactionMessage(String id, String message) {
        try {
            Message<String> strMessage = MessageBuilder.withPayload(message)
                    .setHeader(RocketMQHeaders.KEYS, id)
                    .build();
            TransactionSendResult result = rocketMQTemplate.sendMessageInTransaction(topic, strMessage, id);
            if (result.getSendStatus() == SendStatus.SEND_OK) {
                return Result.ok("发送事务消息成功!消息ID为:" + result.getMsgId());
            }
            return Result.build(null, ResultCodeEnum.TRANSACTION_SEND_FAILED);
        } catch (Exception e) {
            log.warn("事务消息发送异常, id={}", id, e);
            return Result.build(null, ResultCodeEnum.TRANSACTION_SEND_FAILED);
        }
    }
}
