package com.budou.incentive.service;

public interface InventoryDemoService {

    /**
     * 基于 Redis + Lua 的原子扣减示例：
     * 尝试为指定奖品占用 1 份库存。
     *
     * @param awardId 奖品 ID
     * @return true 表示本次成功占用库存；false 表示无库存或占用失败
     */
    boolean tryAcquireInventory(Long awardId);
}

