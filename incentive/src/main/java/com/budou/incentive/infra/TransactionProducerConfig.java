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
                // 半消息发送成功后的本地事务：创建 status=0 的预分配记录，再决定提交或回滚消息。
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
                // 同一用户和奖品只允许一个线程执行预建单，避免并发创建多条待处理记录。
                boolean lock = redisDao.setnx(lockKey, Thread.currentThread().getId(), 300L);
                if (!lock) {
                    return LocalTransactionState.ROLLBACK_MESSAGE;
                }

                try {
                    String statusKey = buildStatusKey(userId, awardId);
                    Integer status = (Integer) redisDao.get(statusKey);
                    // 已存在待处理或成功状态时，当前半消息不应再次进入消费链路。
                    if (status != null && status >= 0) {
                        return LocalTransactionState.ROLLBACK_MESSAGE;
                    }

                    UserAward userAward = new UserAward(id, userId, awardId, 0, new Date(), new Date());
                    int rows = userAwardMapper.insert(userAward);
                    if (rows > 0) {
                        // 数据库记录是事务回查依据，Redis 状态用于加速入口校验和结果查询。
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
                // Broker 未收到明确结果时会回查。必须核对当前消息自己的订单 id，不能用
                // userId+awardId 判断，否则另一笔待处理订单可能让本消息被错误提交。
                Map<String, Object> data;
                try {
                    data = objectMapper.readValue(new String(messageExt.getBody(), StandardCharsets.UTF_8), Map.class);
                } catch (JsonProcessingException e) {
                    log.warn("事务回查解析消息失败", e);
                    throw new RuntimeException(e);
                }
                Long id = Long.valueOf(String.valueOf(data.get("id")));
                Integer status = userAwardMapper.selectStatusById(id);
                // 只要精确订单记录存在，就说明预建单已经落库，本消息应提交给消费者。
                if (status != null) {
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
