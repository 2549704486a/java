package com.budou.incentive.utils;

import com.budou.incentive.dao.mapper.AwardConfigMapper;
import com.budou.incentive.dao.mapper.AwardInventorySplitMapper;
import com.budou.incentive.dao.mapper.UserCurrencyMapper;
import com.budou.incentive.dao.model.AwardConfig;
import com.budou.incentive.dao.model.AwardInventorySplit;
import com.budou.incentive.dao.redis.RedisDao;
import jakarta.annotation.PostConstruct;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Component;

import java.util.List;

@Component
public class CacheWarmer {
    @Autowired
    public RedisDao redisDao;

    @Autowired
    public AwardInventorySplitMapper inventorySplitMapper;

    @Autowired
    public AwardConfigMapper awardConfigMapper;

    @Autowired
    public UserCurrencyMapper userCurrencyMapper;

    @PostConstruct
    public void warm(){
        List<AwardInventorySplit> splits = inventorySplitMapper.select(6L);
        for(AwardInventorySplit split : splits){
            String awardInventorySplitKey = "award_inventory_split:" + 6;
            redisDao.hmSet(
                    awardInventorySplitKey,
                    "splitId:" + split.getSplitId(),
                    split.getInventory());
        }

        AwardConfig awardConfig = awardConfigMapper.selectAwardInfo(6L);
        redisDao.set("award_config:price:" + 6, awardConfig.getPrice());
        redisDao.set("award_config:isOverSell:" + 6, awardConfig.getIsOverSell());
        redisDao.set("award_config:inventory:" + 6, awardConfig.getInventory());
        redisDao.set("award_config:endTime:" + 6,awardConfig.getEndTime());
    }
}
