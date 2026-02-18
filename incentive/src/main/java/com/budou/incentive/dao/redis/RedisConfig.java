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
/**
 * 这个配置类是对Spring Boot的Redis自动配置进行了自定义扩展。让我来解释它的作用和工作原理：
 * RedisConfig配置类的作用
 * 这个配置类主要是定制化RedisTemplate，用以改变默认的序列化方式。虽然Spring Boot已经自动配置了RedisTemplate，
 * 但默认使用的是JDK序列化，这个配置类通过创建一个新的Bean来覆盖默认配置。即发挥@ConditionalOnMissingBean的作用，
 * 阻止RedisAutoConfiguration创建默认的RedisTemplate
 *
 * 1关键部分解析
 * 1.1@Configuration注解
 * 标识这是一个Spring配置类，Spring会在启动时处理这个类
 *
 * 1.2@Bean方法
 * 定义了一个Bean创建方法，Spring将调用它并管理返回的对象
 * 方法参数RedisConnectionFactory由Spring自动注入(这是自动配置已经创建好的)
 *
 * 2与自动配置的关系
 *
 * 2.1复用自动配置的组件
 * 方法注入的RedisConnectionFactory来自Spring Boot的自动配置
 * 这体现了Spring Boot的设计理念：自动配置提供基础组件，开发者可以基于这些组件进行扩展
 *
 * 2.2覆盖默认配置
 *
 * Spring Boot提供的默认RedisTemplate使用JDK序列化
 * 这个配置类创建新的RedisTemplate Bean覆盖了默认实现
 * 这是通过@ConditionalOnMissingBean条件机制实现的(你的Bean会先于自动配置的Bean被考虑)
 *
 * 3为什么需要这个配置类
 * 3.1更好的序列化选择
 * JDK序列化(默认)的缺点：
 * 序列化结果不可读
 * 需要完整的类信息
 * 占用空间大，效率低
 * JSON序列化的优势：
 * 人类可读
 * 跨语言兼容
 * 通常更紧凑
 * 3.2类型指定
 *
 * 将键的类型明确为String(最常用的Redis键类型)
 * 将值的类型指定为Object，增加灵活性
 *
 * 这个配置类体现了Spring Boot的精髓：约定优于配置，但保留配置的能力。
 * Spring Boot提供了开箱即用的自动配置，但同时为你保留了通过明确的配置类进行定制的能力，满足特定需求。
 */