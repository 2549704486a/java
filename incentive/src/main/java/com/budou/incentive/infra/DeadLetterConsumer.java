package com.budou.incentive.infra;

import com.budou.incentive.dao.mapper.AwardInventorySplitMapper;
import com.budou.incentive.dao.mapper.AwardConfigMapper;
import com.budou.incentive.dao.mapper.UserAwardMapper;
import com.budou.incentive.dao.mapper.UserCurrencyMapper;
import com.budou.incentive.dao.model.AwardInventorySplit;
import com.budou.incentive.dao.model.UserAward;
import com.budou.incentive.dao.model.UserCurrency;
import com.budou.incentive.dao.redis.RedisDao;
import com.budou.incentive.service.ConsumerService;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.apache.rocketmq.client.consumer.listener.ConsumeConcurrentlyContext;
import org.apache.rocketmq.client.consumer.listener.ConsumeConcurrentlyStatus;
import org.apache.rocketmq.client.consumer.listener.MessageListenerConcurrently;
import org.apache.rocketmq.common.message.MessageExt;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

import java.nio.charset.StandardCharsets;
import java.util.*;

@Service
//类实现了 MessageListenerConcurrently 接口，该接口用于处理并发消费的消息。
public class DeadLetterConsumer implements MessageListenerConcurrently {
    @Autowired
    private UserAwardMapper userAwardMapper;

    @Override
    public ConsumeConcurrentlyStatus consumeMessage(List<MessageExt> msgs, ConsumeConcurrentlyContext context) {
        for (MessageExt msg : msgs) {
            System.out.println("TransactionConsumer.consumeMessage:开始消费死信消息...");
            System.out.println("Received message: " + new String(msg.getBody()));

            System.out.println("TransactionConsumer.consumeMessage:开始解析死信消息...");
            //从msg中获取userId和awardId
            ObjectMapper objectMapper = new ObjectMapper();
            Map data;
            try {
                data = objectMapper.readValue(new String(msg.getBody(), StandardCharsets.UTF_8), Map.class);
            } catch (Exception e) {
                throw new RuntimeException(e);
            }
            Long userId = Long.valueOf(String.valueOf(data.get("userId")));
            Long awardId = Long.valueOf(String.valueOf(data.get("awardId")));
            Date updateTime = new Date();
            userAwardMapper.updateStatus(new UserAward(null, userId,
                    awardId, -1, null, updateTime));
        }
        return ConsumeConcurrentlyStatus.CONSUME_SUCCESS;
    }
}