package com.budou.incentive.infra;

import com.budou.incentive.utils.Result;
import com.budou.incentive.utils.ResultCodeEnum;
import lombok.extern.slf4j.Slf4j;
import org.apache.rocketmq.client.producer.LocalTransactionState;
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
            // KEYS 用于在 RocketMQ 中检索消息，payload 保存订单、用户和奖品等业务上下文。
            Message<String> strMessage = MessageBuilder.withPayload(message)
                    .setHeader(RocketMQHeaders.KEYS, id)
                    .build();
            // 该调用会先发送半消息，再同步执行 TransactionListener 中的本地事务回调。
            TransactionSendResult result = rocketMQTemplate.sendMessageInTransaction(topic, strMessage, id);
            // Broker 收到半消息不等于业务受理成功，本地事务明确回滚时不能返回“处理中”。
            if (result.getSendStatus() == SendStatus.SEND_OK
                    && result.getLocalTransactionState() != LocalTransactionState.ROLLBACK_MESSAGE) {
                return Result.ok("发送事务消息成功!消息ID为:" + result.getMsgId());
            }
            return Result.build(null, ResultCodeEnum.TRANSACTION_SEND_FAILED);
        } catch (Exception e) {
            log.warn("事务消息发送异常, id={}", id, e);
            return Result.build(null, ResultCodeEnum.TRANSACTION_SEND_FAILED);
        }
    }
    public boolean sendDelayMessage(String id, String message, int delayLevel) {
        try {
            // 消费端暂时拿不到分片锁时发送普通延时消息，避免立即高频重试。
            Message<String> strMessage = MessageBuilder.withPayload(message)
                    .setHeader(RocketMQHeaders.KEYS, id)
                    .build();
            return rocketMQTemplate.syncSend(topic, strMessage, 5000L, delayLevel).getSendStatus() == SendStatus.SEND_OK;
        } catch (Exception e) {
            log.warn("delayed retry message send failed id={} delayLevel={}", id, delayLevel, e);
            return false;
        }
    }
}
