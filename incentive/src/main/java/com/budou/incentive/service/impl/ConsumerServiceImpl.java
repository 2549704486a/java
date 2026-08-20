package com.budou.incentive.service.impl;

import com.budou.incentive.dao.mapper.*;
import com.budou.incentive.dao.model.AwardInventorySplit;
import com.budou.incentive.dao.model.UserAward;
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
        // 普通奖品的最终一致性事务：幂等占位、扣分片库存、扣积分、完成订单同时成功或回滚。
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
        // 唯一键冲突表示该用户和奖品已经处理过，事务会回滚并由消费者按幂等结果处理。
        idempotentMapper.insert(idempotentKey);

        int row1 = awardInventorySplitMapper.updateInventory(awardInventorySplit);
        if(row1 == 0){
            throw new IllegalStateException("split-inventory-empty");
        }

        int row2 = userCurrencyMapper.deductCurrency(userId, price);
        if(row2 == 0){
            throw new IllegalStateException("currency-not-enough");
        }

        int row3 = userAwardMapper.updateStatus(userAward);
        if(row3 == 0){
            throw new IllegalStateException("user-award-status-update-failed");
        }

    }

    @Transactional
    public void update2(Long id, Long userId, Long awardId, Integer price) {
        // 允许超卖时不扣分片库存，但扣积分和完成当前订单仍处于同一个数据库事务中。
        //更新商品的兑换状态
        UserAward userAward = new UserAward();
        userAward.setId(id);
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
