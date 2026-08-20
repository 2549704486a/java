package com.budou.incentive.infra;

import com.budou.incentive.dao.mapper.UserAwardMapper;
import com.budou.incentive.dao.model.UserAward;
import com.budou.incentive.dao.redis.RedisDao;
import com.budou.incentive.utils.SeckillObservability;
import com.budou.incentive.utils.SeckillRedisKeys;
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
    private static final long FAILED_STATUS_TTL_SECONDS = 300L;

    @Autowired
    private UserAwardMapper userAwardMapper;

    @Autowired
    private RedisDao redisDao;

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

            // 进入死信队列表示常规重试已经耗尽，最终把预分配记录置为失败。
            userAwardMapper.updateStatus(new UserAward(id, userId, awardId, -1, null, updateTime));
            // 覆盖此前缓存的 status=0，否则结果接口会一直向用户返回“处理中”。
            redisDao.set(SeckillRedisKeys.buildStatusKey(userId, awardId), -1, FAILED_STATUS_TTL_SECONDS);
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
