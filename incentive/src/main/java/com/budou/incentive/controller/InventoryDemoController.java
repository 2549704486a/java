package com.budou.incentive.controller;

import com.budou.incentive.service.InventoryDemoService;
import com.budou.incentive.utils.Result;
import com.budou.incentive.utils.ResultCodeEnum;
import jakarta.annotation.Resource;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("inventory/demo")
public class InventoryDemoController {

    @Resource
    private InventoryDemoService inventoryDemoService;

    /**
     * 示例接口：
     * GET /inventory/demo/tryAcquire?awardId=1
     *
     * 高并发下，多次并发调用这个接口，只要 Redis 中 demo:inventory:award:{awardId} 还有余量，
     * 就会有部分请求返回 SUCCESS，直到 Redis 库存扣为 0。
     */
    @GetMapping("tryAcquire")
    public Result<?> tryAcquire(@RequestParam("awardId") Long awardId) {
        boolean ok = inventoryDemoService.tryAcquireInventory(awardId);
        if (ok) {
            return Result.ok("acquire success");
        } else {
            return Result.build("no inventory", ResultCodeEnum.Failed);
        }
    }
}

