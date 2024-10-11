package com.budou.incentive.dao.redis;

import org.redisson.Redisson;
import org.redisson.api.RedissonClient;
import org.redisson.config.Config;
import org.springframework.context.annotation.Bean;
import org.springframework.stereotype.Component;

/**
 * @program: incentive
 * @description:
 * @author: 阿伟
 * @create: 2024-10-10 09:44
 **/
@Component
public class RedissonConfig {
    @Bean
    public RedissonClient redissonClient(){
        Config config = new Config();
        config.useSingleServer()
                .setAddress("redis://127.0.0.1:6379")
                .setConnectionPoolSize(10)
                .setConnectionMinimumIdleSize(2);
        return Redisson.create(config);
    }
}
