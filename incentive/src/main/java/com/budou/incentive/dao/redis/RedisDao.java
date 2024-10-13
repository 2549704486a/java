package com.budou.incentive.dao.redis;

import jakarta.annotation.Resource;
import org.apache.commons.collections4.CollectionUtils;
import org.apache.commons.lang3.BooleanUtils;
import org.redisson.api.RedissonClient;
import org.springframework.data.redis.core.*;
import org.springframework.data.redis.core.script.DefaultRedisScript;
import org.springframework.data.redis.core.script.RedisScript;
import org.springframework.stereotype.Component;

import java.time.Duration;
import java.util.List;
import java.util.Set;
import java.util.concurrent.TimeUnit;

// 标注为Spring组件，表示该类会被Spring管理
@Component
public class RedisDao {
    // 自动注入RedisTemplate实例
    @Resource
    RedisTemplate redisTemplate;

    @Resource
    RedissonClient redissonClient;

    public Set<String> getHashKeys(String key) {
        HashOperations<String, String, Integer> ops = redisTemplate.opsForHash();
        return ops.keys(key);
    }

    public Long getHashSize(String key) {
        HashOperations<String, String, Integer> ops = redisTemplate.opsForHash();
        return ops.size(key);
    }

    //执行lua脚本
    public Boolean executeScript(String script, List<String> keys, Object... args) {
        //构造RedisScript对象
        RedisScript<Integer> redisScript = new DefaultRedisScript<>(script, Integer.class);
        //执行lua脚本
        Integer result = (Integer) redisTemplate.execute(redisScript, keys, args);

        return result == 1 ? true : false;
    }

    public boolean set(final String key, Object value) {
        boolean result = false;
        try {
            // ValueOperations 是 Spring Data Redis 中的一个接口，提供了一系列操作字符串类型值的方法。
            //泛型参数 <String, Object> 表示：键（key）的类型为 String，值（value）的类型为 Object。
            //redisTemplate 是 RedisTemplate<String, Object> 类型的实例，通过 Spring 注入（在前面的代码中使用 @Resource 注解）。
            //RedisTemplate 提供了多种与 Redis 进行交互的方法。
            //opsForValue() 是 RedisTemplate 类中的一个方法，用于获取 ValueOperations<String, Object> 实例。
            //ValueOperations 提供了一系列操作 Redis 字符串类型值的方法，如 set、get、getAndSet 等。
//            String json = objectMapper.writeValueAsString(value);
//            redisTemplate.opsForValue().set(key, json);
            redisTemplate.opsForValue().set(key, value);
            result = true;
        } catch (Exception e) {
            e.printStackTrace();
        }
        return result;
    }

    public Long increment(String key){
        return redisTemplate.opsForValue().increment(key);
    }

    public void hdcre(String key1, String key2, Integer value){
        redisTemplate.opsForHash().increment(key1, key2 ,value);
    }

    public void decrement(String key){
        redisTemplate.opsForValue().decrement(key);
    }

    public boolean setnx(String key, Object value, Long timeout){
        Duration durationTimeout = Duration.ofSeconds(timeout);
        boolean success = redisTemplate.opsForValue().setIfAbsent(key, value, durationTimeout);
        return success;
    }

    public void expire(String key, Long timeout){
        redisTemplate.expire(key, timeout, TimeUnit.SECONDS);
    }

    public boolean set(final String key, Object value, Long expireTime) {
        boolean result = false;
        try {
            ValueOperations<String, Object> operations = redisTemplate.opsForValue();
            operations.set(key, value);
            // 设置指定键的过期时间，以秒为单位
            redisTemplate.expire(key, expireTime, TimeUnit.SECONDS);
            result = true;
        } catch (Exception e) {
            e.printStackTrace();
        }
        return result;
    }

    public boolean getAndSet(final String key, String value) {
        boolean result = false;
        try {
            redisTemplate.opsForValue().getAndSet(key, value);
            result = true;
        } catch (Exception e) {
            e.printStackTrace();
        }
        return result;
    }

    //final String... keys，这是一个可变长度参数，表示可以传入多个 String 类型的键。
    public void remove(final String... keys) {
        for (String key : keys) {
            remove(key);
        }
    }

    //final String pattern，表示用于匹配键的模式字符串
    public void removePattern(final String pattern) {
        //调用 redisTemplate 的 keys 方法，根据指定的模式获取所有匹配的键
        Set<String> keys = redisTemplate.keys(pattern);
        //使用 CollectionUtils.isNotEmpty 方法检查键集合是否不为空。
        //CollectionUtils 是 Apache Commons Collections 工具类，isNotEmpty 方法用于检查集合是否不为空。
        if (CollectionUtils.isNotEmpty(keys)) {
            redisTemplate.delete(keys);
        }
    }

    public void remove(final String key) {
        if (exists(key)) {
            redisTemplate.delete(key);
        }
    }

    public boolean exists(final String key) {
        Boolean isExists = redisTemplate.hasKey(key);
        // 使用 BooleanUtils.isTrue 方法将 Boolean 类型的 isExists 转换为 boolean 类型，并返回结果。
        return BooleanUtils.isTrue(isExists);
    }

    public Object get(final String key) {
        ValueOperations<String, Object> operations = redisTemplate.opsForValue();
        return operations.get(key);
    }

    //String key: 哈希表的键，表示哈希表的名称，Object hashKey: 哈希表中的字段键，Object value: 哈希表中的字段值。
    public void hmSet(String key, Object hashKey, Object value) {
        HashOperations<String, Object, Object> hash = redisTemplate.opsForHash();
        //调用 HashOperations 对象的 put 方法，在指定的哈希表 key 中添加字段 hashKey 和对应的值 value。
        hash.put(key, hashKey, value);
    }

    public Object hmGet(String key, Object hashKey) {
        HashOperations<String, Object, Object> hash = redisTemplate.opsForHash();
        return hash.get(key, hashKey);
    }

    public void lPush(String k, Object v) {
        // 获取ListOperations对象，用于操作Redis中的列表
        ListOperations<String, Object> list = redisTemplate.opsForList();
        //调用 ListOperations 对象的 rightPush 方法，将值 v 插入到指定列表 k 的右端。
        list.rightPush(k, v);
    }

    public List<Object> lRange(String k, long l, long l1) {
        ListOperations<String, Object> list = redisTemplate.opsForList();
        // 返回指定列表k中从索引l到索引l1范围内的元素
        return list.range(k, l, l1);
    }

    public void lset(String key, int index, Object value){
        redisTemplate.opsForList().set(key, index, value);
    }

    public void addSet(String key, Object value) {
        SetOperations<String, Object> set = redisTemplate.opsForSet();
        set.add(key, value);
    }

    public void removeSetAll(String key) {
        // 获取SetOperations对象，用于操作Redis中的集合
        SetOperations<String, Object> set = redisTemplate.opsForSet();
        // 获取指定集合key中的所有元素
        Set<Object> objectSet = set.members(key);
        if (objectSet != null && !objectSet.isEmpty()) {
            for (Object o : objectSet) {
                set.remove(key, o);
            }
        }
    }

    public Boolean isMember(String key, Object member) {
        SetOperations<String, Object> set = redisTemplate.opsForSet();
        return set.isMember(key, member);
    }

    public Set<Object> setMembers(String key) {
        SetOperations<String, Object> set = redisTemplate.opsForSet();
        return set.members(key);
    }

    //double score: 值对应的分数，用于在有序集合中排序。
    public void zAdd(String key, Object value, double source) {
        // 获取ZSetOperations对象，用于操作Redis中的有序集合
        ZSetOperations<String, Object> zset = redisTemplate.opsForZSet();
        // 将指定的元素及其分数添加到有序集合key中
        zset.add(key, value, source);
    }

    public Set<Object> rangeByScore(String key, double source, double source1) {
        ZSetOperations<String, Object> zSet = redisTemplate.opsForZSet();
        return zSet.rangeByScore(key, source, source1);
    }

    public Set<Object> range(String key, Long source, Long source1) {
        ZSetOperations<String, Object> zSet = redisTemplate.opsForZSet();
        return zSet.range(key, source, source1);
    }

    public Set<Object> reverseRange(String key, Long source, Long source1) {
        ZSetOperations<String, Object> zSet = redisTemplate.opsForZSet();
        return zSet.reverseRange(key, source, source1);
    }


}
