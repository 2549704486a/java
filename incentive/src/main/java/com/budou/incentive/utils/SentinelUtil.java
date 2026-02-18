package com.budou.incentive.utils;

import com.alibaba.csp.sentinel.slots.block.BlockException;

/**
 * @program: incentive-事务消息
 * @description:
 * @author: 阿伟
 * @create: 2024-10-26 20:18
 **/
public class SentinelUtil {
    public static Result handleException(Long userId, Long awardId, BlockException e){
        return Result.fail("服务器繁忙，请稍后重试");
    }
}
