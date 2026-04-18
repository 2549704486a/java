package com.budou.incentive.utils;

import com.budou.incentive.config.CacheWarmProperties;
import com.budou.incentive.dao.mapper.AwardConfigMapper;
import com.budou.incentive.dao.mapper.AwardInventorySplitMapper;
import com.budou.incentive.dao.model.AwardConfig;
import com.budou.incentive.dao.model.AwardInventorySplit;
import com.budou.incentive.dao.redis.RedisDao;
import jakarta.annotation.PostConstruct;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Component;

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
    public CacheWarmProperties cacheWarmProperties;

    @PostConstruct
    public void warm(){
        for (Long awardId : cacheWarmProperties.getAwardIds()) {
            if (awardId == null) {
                continue;
            }
            warmAward(awardId);
        }
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
    }
}
