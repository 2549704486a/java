package com.budou.incentive.infra;
import jakarta.annotation.Resource;
import org.apache.rocketmq.client.consumer.DefaultMQPushConsumer;
import org.apache.rocketmq.spring.annotation.RocketMQMessageListener;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.Bean;

//@Configuration: 注解标明这是一个Spring配置类，用于定义Bean和配置应用程序的相关设置。
@Configuration
public class DeadLetterConsumerConfig {
    @Value("${rocketmq.name-server}")
    private String nameServer;

    @Value("${rocketmq.dead-letter-consumer.group}")
    private String consumerGroup;

    @Value("${rocketmq.dead-letter-consumer.topic}")
    private String topic;

    @Resource
    private DeadLetterConsumer deadLetterConsumer;
    //注解标明这是一个Spring Bean，方法返回一个要注册到Spring容器中的Bean。initMethod和destroyMethod分别指定Bean的初始化和销毁方法。
    @Bean(name = "myConsumer", initMethod = "start", destroyMethod = "shutdown")
    public DefaultMQPushConsumer createConsumer() throws Exception {
        //创建一个DefaultMQPushConsumer实例，并设置消费者组名。
        DefaultMQPushConsumer consumer = new DefaultMQPushConsumer(consumerGroup);
        //设置RocketMQ NameServer地址。
        consumer.setNamesrvAddr(nameServer);
        //订阅指定的主题和标签（使用*表示订阅所有标签）。
        consumer.subscribe(topic,"*");
        //注册消息监听器，处理接收到的消息。
        consumer.registerMessageListener(deadLetterConsumer);
        return consumer;
    }
}
