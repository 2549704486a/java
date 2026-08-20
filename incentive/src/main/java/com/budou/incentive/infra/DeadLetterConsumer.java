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
            long messageStartMillis = resolveMessageStartMillis(data, msg);
            Date updateTime = new Date();

            userAwardMapper.updateStatus(new UserAward(id, userId, awardId, -1, null, updateTime));
            seckillObservability.recordDeadLetter(id, userId, awardId,
                    Math.max(System.currentTimeMillis() - messageStartMillis, 0L));
        }
        return ConsumeConcurrentlyStatus.CONSUME_SUCCESS;
    }

    private long resolveMessageStartMillis(Map<String, Object> data, MessageExt msg) {
        Object messageTimeMillis = data.get("messageTimeMillis");
        if (messageTimeMillis == null) {
            return msg.getBornTimestamp();
        }
        try {
            return Long.parseLong(String.valueOf(messageTimeMillis));
        } catch (NumberFormatException ex) {
            return msg.getBornTimestamp();
        }
    }
}
