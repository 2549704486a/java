package com.budou.incentive.service.impl;

import com.budou.incentive.dao.mapper.*;
import com.budou.incentive.dao.model.AwardInventorySplit;
import com.budou.incentive.dao.model.UserAward;
import com.budou.incentive.dao.model.UserCurrency;
import com.budou.incentive.dao.redis.RedisDao;
import com.budou.incentive.service.ConsumerService;
import jakarta.transaction.Transactional;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

/**
 * @program: incentive
 * @description:
 * @author: 阿伟
 * @create: 2024-10-09 15:07
 **/
@Service
public class ConsumerServiceImpl implements ConsumerService {
    @Autowired
    private RedisDao redisDao;
    @Autowired
    private AwardConfigMapper awardConfigMapper;
    @Autowired
    private AwardInventorySplitMapper awardInventorySplitMapper;
    @Autowired
    private UserCurrencyMapper userCurrencyMapper;
    @Autowired
    private UserAwardMapper userAwardMapper;
    @Autowired
    private InventoryLog inventoryLog;
    @Transactional
    public void update1(AwardInventorySplit awardInventorySplit, UserCurrency userCurrency,
                        UserAward userAward, String lockKey, String lockValue) {
        //执行数据库事务
        awardInventorySplitMapper.updateInventory(awardInventorySplit);
//        inventoryLog.insertLog(userAward.getUserId(), userAward.getAwardId(),
//                awardInventorySplit.getInventory(), awardInventorySplit.getId(),
//                userAward.getCreateTime());
        userCurrencyMapper.updateCurrency(userCurrency);
        userAwardMapper.updateStatus(userAward);

        //执行完后，再确认锁是否有效
//        boolean isLatest = redisDao.get(lockKey).equals(lockValue);
//
//        //如果锁失效，直接抛出异常让事务回滚，认为重新消费一次消息的代价是可以接受的
//        if (isLatest == false) {
//            throw new RuntimeException("ConsumerServiceImpl.update1:分布式锁失效，主动抛出异常，回滚事务");
//        } else {
//            redisLockWithRenewal.releaseLock(lockKey, lockValue);
//            System.out.println("TransactionConsumer.consumeMessage:兑换成功");
//        }
    }

    @Transactional
    public void update2(UserCurrency userCurrency, UserAward userAward){
        userCurrencyMapper.updateCurrency(userCurrency);
        userAwardMapper.updateStatus(userAward);
    }
}
