package com.budou.incentive.service.impl;

import com.budou.incentive.dao.mapper.*;
import com.budou.incentive.dao.model.AwardInventorySplit;
import com.budou.incentive.dao.model.FinishTaskRecord;
import com.budou.incentive.dao.model.UserAward;
import com.budou.incentive.dao.model.UserCurrency;
import com.budou.incentive.dao.redis.RedisDao;
import com.budou.incentive.service.ConsumerService;
import jakarta.transaction.Transactional;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

import java.util.Date;

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
    @Autowired
    private IdempotentMapper idempotentMapper;
    @Transactional
    public void update1(Long id, Long userId, Long awardId, Integer price, Long splitId) {

        //扣减分库存
        AwardInventorySplit awardInventorySplit = new AwardInventorySplit();
        awardInventorySplit.setSplitId(splitId);
        awardInventorySplit.setAwardId(awardId);

        //更新商品的兑换状态
        UserAward userAward = new UserAward();
        userAward.setId(id);
        userAward.setUpdateTime(new Date());
        userAward.setStatus(1);//status=1表示兑换成功

        String idempotentKey = "userId:" + userId + "-awardId:" + awardId;
        idempotentMapper.insert(idempotentKey);

        int row1 = awardInventorySplitMapper.updateInventory(awardInventorySplit);
        int row2 = userCurrencyMapper.deductCurrency(userId, price);
        int row3 = userAwardMapper.updateStatus(userAward);
        if(row1 == 0 || row2 == 0 || row3 == 0){
            throw new RuntimeException();
        }

    }

    @Transactional
    public void update2(Long id, Long userId, Long awardId, Integer price) {

        //更新商品的兑换状态
        UserAward userAward = new UserAward();
        userAward.setUserId(userId);
        userAward.setAwardId(awardId);
        userAward.setUpdateTime(new Date());
        userAward.setStatus(1);//status=1表示兑换成功

        int row1 = userCurrencyMapper.deductCurrency(userId, price);
        int row2 = userAwardMapper.updateStatus(userAward);
        if(row1 == 0 || row2 == 0){
            throw new RuntimeException();
        }
    }
}
