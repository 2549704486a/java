package com.budou.incentive.infra;

import com.budou.incentive.dao.mapper.UserAwardMapper;
import com.budou.incentive.dao.model.UserAward;
import com.budou.incentive.dao.redis.RedisDao;
import com.budou.incentive.utils.SeckillRedisKeys;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.extern.slf4j.Slf4j;
import org.apache.rocketmq.client.producer.LocalTransactionState;
import org.apache.rocketmq.client.producer.TransactionListener;
import org.apache.rocketmq.client.producer.TransactionMQProducer;
import org.apache.rocketmq.common.message.Message;
import org.apache.rocketmq.common.message.MessageExt;
import org.apache.rocketmq.spring.core.RocketMQTemplate;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

import java.nio.charset.StandardCharsets;
import java.util.Date;
import java.util.Map;

@Configuration
@Slf4j
public class TransactionProducerConfig {

    @Autowired
    private UserAwardMapper userAwardMapper;

    @Value("${rocketmq.producer.group}")
    private String producerGroup;

    @Value("${rocketmq.name-server}")
    private String nameServer;

    @Autowired
    private RedisDao redisDao;

    @Autowired
    private ObjectMapper objectMapper;

    @Bean
    public TransactionListener transactionListener() {
        return new TransactionListener() {
            @Override
            public LocalTransactionState executeLocalTransaction(Message message, Object o) {
                Map<String, Object> data;
                try {
                    data = objectMapper.readValue(new String(message.getBody(), StandardCharsets.UTF_8), Map.class);
                } catch (Exception e) {
                    throw new RuntimeException(e);
                }
                Long userId = Long.valueOf(String.valueOf(data.get("userId")));
                Long awardId = Long.valueOf(String.valueOf(data.get("awardId")));
                Long id = Long.valueOf(String.valueOf(data.get("id")));
                String lockKey = "createOrder:award:" + awardId + ":user:" + userId;
                boolean lock = redisDao.setnx(lockKey, Thread.currentThread().getId(), 300L);
                if (!lock) {
                    return LocalTransactionState.ROLLBACK_MESSAGE;
                }

                try {
                    String statusKey = buildStatusKey(userId, awardId);
                    Integer status = (Integer) redisDao.get(statusKey);
                    if (status != null && status >= 0) {
                        return LocalTransactionState.ROLLBACK_MESSAGE;
                    }

                    UserAward userAward = new UserAward(id, userId, awardId, 0, new Date(), new Date());
                    int rows = userAwardMapper.insert(userAward);
                    if (rows > 0) {
                        redisDao.set(statusKey, 0);
                        return LocalTransactionState.COMMIT_MESSAGE;
                    }
                    return LocalTransactionState.ROLLBACK_MESSAGE;
                } finally {
                    redisDao.remove(lockKey);
                }
            }

            @Override
            public LocalTransactionState checkLocalTransaction(MessageExt messageExt) {
                Map<String, Object> data;
                try {
                    data = objectMapper.readValue(new String(messageExt.getBody(), StandardCharsets.UTF_8), Map.class);
                } catch (JsonProcessingException e) {
                    log.warn("事务回查解析消息失败", e);
                    throw new RuntimeException(e);
                }
                Long userId = Long.valueOf(String.valueOf(data.get("userId")));
                Long awardId = Long.valueOf(String.valueOf(data.get("awardId")));
                Integer count = userAwardMapper.selectUnhandleOrder(userId, awardId, 0);
                if (count != null && count > 0) {
                    return LocalTransactionState.COMMIT_MESSAGE;
                }
                return LocalTransactionState.ROLLBACK_MESSAGE;
            }
        };
    }

    @Bean
    public TransactionMQProducer transactionalProducer() {
        TransactionMQProducer producer = new TransactionMQProducer(producerGroup);
        producer.setNamesrvAddr(nameServer);
        producer.setTransactionListener(transactionListener());
        return producer;
    }

    @Bean
    public RocketMQTemplate rocketMqTemplate() {
        RocketMQTemplate rocketMqTemplate = new RocketMQTemplate();
        rocketMqTemplate.setProducer(transactionalProducer());
        return rocketMqTemplate;
    }

    private String buildStatusKey(Long userId, Long awardId) {
        return SeckillRedisKeys.buildStatusKey(userId, awardId);
    }

}
