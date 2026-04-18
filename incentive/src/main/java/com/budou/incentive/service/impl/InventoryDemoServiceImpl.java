package com.budou.incentive.service.impl;

import com.budou.incentive.dao.mapper.AwardConfigMapper;
import com.budou.incentive.dao.redis.RedisDao;
import com.budou.incentive.service.InventoryDemoService;
import jakarta.annotation.Resource;
import org.springframework.stereotype.Service;

import java.util.Collections;

@Service
public class InventoryDemoServiceImpl implements InventoryDemoService {

    @Resource
    private RedisDao redisDao;

    @Resource
    private AwardConfigMapper awardConfigMapper;

    /**
     * Demo 方案：
     * 1）懒加载：当 Redis 中没有库存时，从 DB 读一次初始库存并写入 Redis。
     * 2）使用 Lua 脚本在 Redis 中原子地执行「先判断后扣减」：
     *    - 若 key 不存在或库存 <= 0，则返回 0（失败）；
     *    - 否则执行 DECR 并返回 1（成功）。
     *
     * 说明：DB 库存的最终落账可以通过异步任务 / binlog 方案来做，这个方法主要演示高并发下的原子扣减。
     */
    @Override
    public boolean tryAcquireInventory(Long awardId) {
        if (awardId == null || awardId <= 0) {
            return false;
        }

        String key = "demo:inventory:award:" + awardId;

        // 懒加载：Redis 中没有时，从 DB 初始化一次
        Object cacheVal = redisDao.get(key);
        if (cacheVal == null) {
            Integer dbInventory = awardConfigMapper.selectInventory(awardId);
            if (dbInventory == null || dbInventory <= 0) {
                return false;
            }
            redisDao.set(key, dbInventory);
        }

        // Lua 脚本：原子判断并扣减 1
        String script = """
                local val = redis.call('GET', KEYS[1])
                if (not val) then
                    return 0
                end
                local n = tonumber(val)
                if (n == nil or n <= 0) then
                    return 0
                end
                redis.call('DECR', KEYS[1])
                return 1
                """;

        Boolean success = redisDao.executeScript(script, Collections.singletonList(key));
        return Boolean.TRUE.equals(success);
    }
}

