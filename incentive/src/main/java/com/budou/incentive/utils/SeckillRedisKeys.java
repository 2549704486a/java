package com.budou.incentive.utils;

public final class SeckillRedisKeys {

    private SeckillRedisKeys() {
    }

    public static String buildStatusKey(Long userId, Long awardId) {
        return "user_award:status:" + userId + ":" + awardId;
    }

    public static String buildIdempotentKey(Long userId, Long awardId) {
        return "userId:" + userId + "-awardId:" + awardId;
    }

    public static String buildAwardInventoryKey(Long awardId) {
        return "award_config:inventory:" + awardId;
    }
}
