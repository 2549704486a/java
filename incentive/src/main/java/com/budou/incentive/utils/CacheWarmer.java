package com.budou.incentive.utils;

import com.budou.incentive.config.CacheWarmProperties;
import com.budou.incentive.dao.mapper.AwardConfigMapper;
import com.budou.incentive.dao.mapper.AwardInventorySplitMapper;
import com.budou.incentive.dao.mapper.UserCurrencyMapper;
import com.budou.incentive.dao.model.AwardConfig;
import com.budou.incentive.dao.model.AwardInventorySplit;
import com.budou.incentive.dao.model.UserCurrency;
import com.budou.incentive.dao.redis.RedisDao;
import com.github.benmanes.caffeine.cache.Cache;
import jakarta.annotation.PostConstruct;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Component;

import java.util.Date;
import java.util.List;

@Component
@Slf4j
@ConditionalOnProperty(prefix = "cache.warm", name = "enabled", havingValue = "true", matchIfMissing = true)
public class CacheWarmer {
    @Autowired
    public RedisDao redisDao;

    @Autowired
    public AwardInventorySplitMapper inventorySplitMapper;

    @Autowired
    public AwardConfigMapper awardConfigMapper;

    @Autowired
    public UserCurrencyMapper userCurrencyMapper;

    @Autowired
    public CacheWarmProperties cacheWarmProperties;

    @Autowired
    @Qualifier("awardPriceCache")
    private Cache<Long, Integer> awardPriceCache;

    @Autowired
    @Qualifier("awardEndTimeCache")
    private Cache<Long, Date> awardEndTimeCache;

    @Autowired
    @Qualifier("awardInventoryCache")
    private Cache<Long, Integer> awardInventoryCache;

    @Autowired
    @Qualifier("userCurrencyCache")
    private Cache<Long, Integer> userCurrencyCache;

    @PostConstruct
    public void warm(){
        for (Long awardId : cacheWarmProperties.getAwardIds()) {
            if (awardId == null) {
                continue;
            }
            warmAward(awardId);
        }
        warmUserCurrency();
    }

    private void warmAward(Long awardId) {
        List<AwardInventorySplit> splits = inventorySplitMapper.select(awardId);
        for (AwardInventorySplit split : splits) {
            String awardInventorySplitKey = "award_inventory_split:" + awardId;
            redisDao.hmSet(
                    awardInventorySplitKey,
                    "splitId:" + split.getSplitId(),
                    split.getInventory());
        }

        AwardConfig awardConfig = awardConfigMapper.selectAwardInfo(awardId);
        if (awardConfig == null) {
            log.warn("缓存预热跳过，未找到奖品配置: awardId={}", awardId);
            return;
        }
        redisDao.set("award_config:price:" + awardId, awardConfig.getPrice());
        redisDao.set("award_config:isOverSell:" + awardId, awardConfig.getIsOverSell());
        redisDao.set("award_config:inventory:" + awardId, awardConfig.getInventory());
        redisDao.set("award_config:endTime:" + awardId, awardConfig.getEndTime());
        awardPriceCache.put(awardId, awardConfig.getPrice());
        awardEndTimeCache.put(awardId, awardConfig.getEndTime());
        awardInventoryCache.put(awardId, awardConfig.getInventory());
    }

    private void warmUserCurrency() {
        if (!cacheWarmProperties.isUserCurrencyEnabled()) {
            return;
        }

        Long minUserId = cacheWarmProperties.getUserCurrencyMinUserId();
        Long maxUserId = cacheWarmProperties.getUserCurrencyMaxUserId();
        if (minUserId == null || maxUserId == null || minUserId > maxUserId) {
            log.warn("用户积分预热参数非法，跳过预热: minUserId={}, maxUserId={}", minUserId, maxUserId);
            return;
        }

        List<UserCurrency> userCurrencies = userCurrencyMapper.selectRange(minUserId, maxUserId);
        for (UserCurrency userCurrency : userCurrencies) {
            if (userCurrency == null || userCurrency.getUserId() == null || userCurrency.getCurrency() == null) {
                continue;
            }
            String userCurrencyKey = "user:currency:" + userCurrency.getUserId();
            redisDao.set(userCurrencyKey, userCurrency.getCurrency());
            userCurrencyCache.put(userCurrency.getUserId(), userCurrency.getCurrency());
        }
        log.info("用户积分预热完成，userId区间=[{}, {}]，共加载 {} 条", minUserId, maxUserId, userCurrencies.size());
    }
}
