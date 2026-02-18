package com.budou.incentive.infra;

import com.budou.incentive.dao.mapper.UserAwardMapper;
import com.budou.incentive.dao.model.UserAward;
import com.budou.incentive.dao.redis.RedisDao;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.apache.rocketmq.client.producer.LocalTransactionState;
import org.apache.rocketmq.common.message.Message;
import org.apache.rocketmq.common.message.MessageExt;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Configuration;
import org.apache.rocketmq.client.producer.TransactionListener;
import org.apache.rocketmq.client.producer.TransactionMQProducer;
import org.springframework.context.annotation.Bean;
import org.apache.rocketmq.spring.core.RocketMQTemplate;

import java.nio.charset.StandardCharsets;
import java.util.Date;
import java.util.Map;

//@Configuration: 注解标明这是一个Spring配置类，用于定义Bean和配置应用程序的相关设置。
@Configuration
public class TransactionProducerConfig {

    @Autowired
    private UserAwardMapper userAwardMapper;

    @Value("${rocketmq.producer.group}")
    private String producerGroup;

    @Value("${rocketmq.name-server}")
    private String nameServer;

    @Autowired
    private RedisDao redisDao;
    //定义一个TransactionListener Bean，用于处理事务消息的本地事务和事务回查。
    @Bean
    public TransactionListener transactionListener() {
        return new TransactionListener() {
            @Override
            public LocalTransactionState executeLocalTransaction(Message message, Object o) {
                //执行本地事务
                ObjectMapper objectMapper = new ObjectMapper();
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
                    // 幂等检查：是否已存在未处理订单
                    Integer count = userAwardMapper.selectUnhandleOrder(userId, awardId, 0);
                    if (count != null && count > 0) {
                        return LocalTransactionState.ROLLBACK_MESSAGE;
                    }

                    UserAward userAward = new UserAward(id, userId, awardId, 0, new Date(), new Date());
                    int rows = userAwardMapper.insert(userAward);

                    // 返回事务提交状态。
                    if (rows > 0) {
                        return LocalTransactionState.COMMIT_MESSAGE;
                    } else {
                        return LocalTransactionState.ROLLBACK_MESSAGE;
                    }
                } finally {
                    redisDao.remove(lockKey);
                }
            }

            @Override
            //MessageExt 对象，表示RocketMQ中的扩展消息。它不仅包含消息的基本信息（如消息体、主题、标签、键），
            //还包括一些扩展的元数据（如消息ID、存储信息、队列信息等）
            public LocalTransactionState checkLocalTransaction(MessageExt messageExt) {
                // 检查本地事务执行结果（依赖数据库而非缓存，更加可靠）
                ObjectMapper objectMapper = new ObjectMapper();
                Map<String, Object> data;
                try {
                    data = objectMapper.readValue(new String(messageExt.getBody(), StandardCharsets.UTF_8), Map.class);
                } catch (JsonProcessingException e) {
                    throw new RuntimeException(e);
                }
                Long userId = Long.valueOf(String.valueOf(data.get("userId")));
                Long awardId = Long.valueOf(String.valueOf(data.get("awardId")));

                // 是否已有未处理订单：有则认为本地事务成功，提交消息；否则回滚
                Integer count = userAwardMapper.selectUnhandleOrder(userId, awardId, 0);
                if (count != null && count > 0) {
                    return LocalTransactionState.COMMIT_MESSAGE;
                }
                return LocalTransactionState.ROLLBACK_MESSAGE;
            }
        };
    }
    //定义一个TransactionMQProducer Bean，用于发送事务消息。
    @Bean
    public TransactionMQProducer transactionalProducer() {
        //创建一个TransactionMQProducer实例并设置生产者组名。
        TransactionMQProducer producer = new TransactionMQProducer(producerGroup);
        //设置NameServer地址。
        producer.setNamesrvAddr(nameServer);
        // 设置事务监听器。
        producer.setTransactionListener(transactionListener());
        return producer;
    }

    //定义一个RocketMQTemplate Bean，用于发送事务消息。
    @Bean
    public RocketMQTemplate rocketMqTemplate() {
        //创建一个RocketMQTemplate实例。
        RocketMQTemplate rocketMqTemplate = new RocketMQTemplate();
        //设置事务生产者。
        rocketMqTemplate.setProducer(transactionalProducer());
        return rocketMqTemplate;
    }
}
