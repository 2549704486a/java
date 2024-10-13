package com.budou.incentive.service.impl;
import com.budou.incentive.dao.mapper.AwardConfigMapper;
import com.budou.incentive.dao.redis.RedisDao;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;

import java.util.Date;
import java.util.Set;

@Service
public class DataSyncService {

    @Autowired
    private RedisDao redisDao;

    @Autowired
    private AwardConfigMapper awardConfigMapper;

    @Scheduled(fixedRate = 60000) // 每60秒执行一次
    public void syncData() {
        String pattern = "award_config:inventory:*";
        Set<String> keys = redisDao.keys(pattern);
        if (keys != null) {
            for (String key : keys) {
                Integer inventory = (Integer) redisDao.get(key);
                Long awardId = Long.valueOf(key.substring(23));
                // 插入或更新到 MySQL
                awardConfigMapper.update(awardId, inventory, new Date());
            }
        }
    }
}
