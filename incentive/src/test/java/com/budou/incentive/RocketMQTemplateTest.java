package com.budou.incentive;

import org.apache.rocketmq.spring.core.RocketMQListener;
import org.apache.rocketmq.spring.core.RocketMQTemplate;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;

/**
 * @program: incentive-事务消息
 * @description:
 * @author: 阿伟
 * @create: 2024-10-27 14:46
 **/
@SpringBootTest
public class RocketMQTemplateTest {
    @Autowired
    RocketMQTemplate rocketMQTemplate;
    @Test
    public void testProducer() {
        System.out.println("Producer:" + rocketMQTemplate.getProducer());
    }
}
