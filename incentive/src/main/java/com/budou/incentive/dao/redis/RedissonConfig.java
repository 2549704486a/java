package com.budou.incentive.dao.redis;

import org.springframework.boot.autoconfigure.data.redis.RedisProperties;
import org.redisson.Redisson;
import org.redisson.api.RedissonClient;
import org.redisson.config.Config;
import org.redisson.config.SingleServerConfig;
import org.springframework.context.annotation.Bean;
import org.springframework.stereotype.Component;
import org.springframework.util.StringUtils;

import java.time.Duration;

/**
 * @program: incentive
 * @description:
 * @author: 阿伟
 * @create: 2024-10-10 09:44
 **/
@Component
public class RedissonConfig {
    @Bean
    public RedissonClient redissonClient(RedisProperties redisProperties){
        Config config = new Config();
        SingleServerConfig singleServerConfig = config.useSingleServer()
                .setAddress(buildRedisAddress(redisProperties))
                .setConnectionPoolSize(10)
                .setConnectionMinimumIdleSize(2)
                .setDatabase(redisProperties.getDatabase());

        Duration timeout = redisProperties.getTimeout();
        if (timeout != null) {
            singleServerConfig.setTimeout((int) timeout.toMillis());
        }
        if (StringUtils.hasText(redisProperties.getUsername())) {
            singleServerConfig.setUsername(redisProperties.getUsername());
        }
        if (StringUtils.hasText(redisProperties.getPassword())) {
            singleServerConfig.setPassword(redisProperties.getPassword());
        }
        return Redisson.create(config);
    }

    private String buildRedisAddress(RedisProperties redisProperties) {
        String scheme = redisProperties.getSsl().isEnabled() ? "rediss://" : "redis://";
        return scheme + redisProperties.getHost() + ":" + redisProperties.getPort();
    }
}
