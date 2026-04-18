package com.budou.incentive.infra;

import com.budou.incentive.dao.mapper.UserAwardMapper;
import com.budou.incentive.dao.model.UserAward;
import com.budou.incentive.utils.SeckillObservability;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.apache.rocketmq.client.consumer.listener.ConsumeConcurrentlyContext;
import org.apache.rocketmq.client.consumer.listener.ConsumeConcurrentlyStatus;
import org.apache.rocketmq.client.consumer.listener.MessageListenerConcurrently;
import org.apache.rocketmq.common.message.MessageExt;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

import java.nio.charset.StandardCharsets;
import java.util.Date;
import java.util.List;
import java.util.Map;

@Service
public class DeadLetterConsumer implements MessageListenerConcurrently {
    @Autowired
    private UserAwardMapper userAwardMapper;

    @Autowired
    private SeckillObservability seckillObservability;

    @Override
    public ConsumeConcurrentlyStatus consumeMessage(List<MessageExt> msgs, ConsumeConcurrentlyContext context) {
        for (MessageExt msg : msgs) {
            System.out.println("TransactionConsumer.consumeMessage:开始消费死信消息...");
            System.out.println("Received message: " + new String(msg.getBody()));

            System.out.println("TransactionConsumer.consumeMessage:开始解析死信消息...");
            ObjectMapper objectMapper = new ObjectMapper();
            Map<String, Object> data;
            try {
                data = objectMapper.readValue(new String(msg.getBody(), StandardCharsets.UTF_8), Map.class);
            } catch (Exception e) {
                throw new RuntimeException(e);
            }
            Long userId = Long.valueOf(String.valueOf(data.get("userId")));
            Long awardId = Long.valueOf(String.valueOf(data.get("awardId")));
            Long id = Long.valueOf(String.valueOf(data.get("id")));
            long requestStartMillis = resolveRequestStartMillis(data, msg);
            Date updateTime = new Date();

            userAwardMapper.updateStatus(new UserAward(id, userId, awardId, -1, null, updateTime));
            seckillObservability.recordDeadLetter(id, userId, awardId,
                    Math.max(System.currentTimeMillis() - requestStartMillis, 0L));
        }
        return ConsumeConcurrentlyStatus.CONSUME_SUCCESS;
    }

    private long resolveRequestStartMillis(Map<String, Object> data, MessageExt msg) {
        Object requestTimeMillis = data.get("requestTimeMillis");
        if (requestTimeMillis == null) {
            return msg.getBornTimestamp();
        }
        try {
            return Long.parseLong(String.valueOf(requestTimeMillis));
        } catch (NumberFormatException ex) {
            return msg.getBornTimestamp();
        }
    }
}
