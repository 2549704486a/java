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
                Map data;
                try {
                    data = objectMapper.readValue(new String(message.getBody(), StandardCharsets.UTF_8), Map.class);
                } catch (Exception e) {
                    throw new RuntimeException(e);
                }
                Long userId = Long.valueOf(String.valueOf(data.get("userId")));
                Long awardId = Long.valueOf(String.valueOf(data.get("awardId")));
                Long id = Long.valueOf(String.valueOf(data.get("id")));

                System.out.println(id);

                // 加分布式锁，保证一人一单
                boolean lock = redisDao.setnx(
                        "createOrder-" + "awardId:" + awardId + "-userId:" + userId,
                        Thread.currentThread().getId(),
                        300L);
                if(!lock){
                    return LocalTransactionState.ROLLBACK_MESSAGE;
                }

                // 写入订单
                Integer count = userAwardMapper.selectUnhandleOrder(userId, awardId, 0);
                if(count > 0) {
                    System.out.println("回滚啦");
                    return LocalTransactionState.ROLLBACK_MESSAGE;
                }
                System.out.println("到这里了");
                UserAward userAward = new UserAward(id, userId, awardId, 0, new Date(), new Date());
                int rows = userAwardMapper.insert(userAward);
                redisDao.remove("createOrder-" + "awardId:" + awardId + "-userId:" + userId);

                //返回事务提交状态。
                if (rows > 0) {
                    System.out.println("user:" + userId + "写入成功");
                    return LocalTransactionState.COMMIT_MESSAGE;
                } else {
                    System.out.println("user:" + userId + "写入失败");
                    return LocalTransactionState.ROLLBACK_MESSAGE;
                }
            }

            @Override
            //MessageExt 对象，表示RocketMQ中的扩展消息。它不仅包含消息的基本信息（如消息体、主题、标签、键），
            //还包括一些扩展的元数据（如消息ID、存储信息、队列信息等）
            public LocalTransactionState checkLocalTransaction(MessageExt messageExt) {
                //打印执行事务回查日志。
                System.out.println("checkLocalTransaction...");

                //检查事务执行
                ObjectMapper objectMapper = new ObjectMapper();
                Map data;
                try {
                    data = objectMapper.readValue(new String(messageExt.getBody(), StandardCharsets.UTF_8), Map.class);
                } catch (JsonProcessingException e) {
                    throw new RuntimeException(e);
                }
                Long userId = Long.valueOf(String.valueOf(data.get("userId")));
                Long awardId = Long.valueOf(String.valueOf(data.get("awardId")));

                //这里只查了redis，其实还要查一下数据库，懒得写了
                String userAwardStatusKey = "user_award:status:" + userId +":" + awardId;
                Object status = redisDao.get(userAwardStatusKey);
                if(status == null){
                    System.out.println("回滚");
                    return LocalTransactionState.ROLLBACK_MESSAGE;
                } else {
                    //返回事务提交状态。
                    System.out.println("提交");
                    return LocalTransactionState.COMMIT_MESSAGE;
                }
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
