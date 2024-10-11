package com.budou.incentive.dao.redis;


import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.data.redis.connection.RedisConnectionFactory;
import org.springframework.data.redis.core.RedisTemplate;
import org.springframework.data.redis.serializer.GenericJackson2JsonRedisSerializer;
import org.springframework.data.redis.serializer.StringRedisSerializer;


//@Configuration注解标明这是一个Spring配置类，用于配置Spring容器中的Bean。
@Configuration
public class RedisConfig {
    // 定义一个RedisTemplate Bean，用于操作Redis数据库
    //public class RedisConfig: 定义一个名为RedisConfig的公共类，用于配置Redis相关的Bean
    @Bean
    public RedisTemplate<String, Object> redisTemplate(RedisConnectionFactory redisConnectionFactory){

        // 创建一个新的RedisTemplate实例
        RedisTemplate<String, Object> template = new RedisTemplate<>();

        // 设置Redis连接工厂
        template.setConnectionFactory(redisConnectionFactory);

        //设置redis序列化器
        StringRedisSerializer keySerializer = new StringRedisSerializer();
        GenericJackson2JsonRedisSerializer valueSerializer = new GenericJackson2JsonRedisSerializer();

        // 设置键的序列化器
        template.setKeySerializer(keySerializer);
        // 设置值的序列化器
        template.setValueSerializer(valueSerializer);
        // 设置哈希键的序列化器
        template.setHashKeySerializer(keySerializer);
        // 设置哈希值的序列化器
        template.setHashValueSerializer(valueSerializer);
        // 返回配置好的RedisTemplate实例
        return template;
    }

}
