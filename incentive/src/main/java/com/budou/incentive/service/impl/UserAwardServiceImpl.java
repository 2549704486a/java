package com.budou.incentive.service.impl;

import com.budou.incentive.dao.mapper.*;
import com.budou.incentive.dao.model.*;
import com.budou.incentive.dao.redis.RedisDao;
import com.budou.incentive.service.*;
import com.budou.incentive.utils.*;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

import java.util.Date;
import java.util.HashMap;
import java.util.Map;
import java.util.UUID;

@Service
public class UserAwardServiceImpl implements UserAwardService {
    @Autowired
    private TransactionService transactionService;

    @Autowired
    private UserAwardMapper userAwardMapper;

    @Autowired
    private UserCurrencyMapper userCurrencyMapper;

    @Autowired
    private IdempotentMapper idempotentMapper;

    @Autowired
    private RedisDao redisDao;

    @Override
    public Result exchange(Long userId, Long awardId) {
        System.out.println("UserAwardServiceImpl.exchange: exchange, userId = " + userId + "awardId = " + awardId);

        // 前置检查
        if(!check(userId, awardId)){
            return Result.fail("不满足条件");
        }

        //发送事务消息
        Map<String, Object> data = new HashMap<>();

        /**
         * 两种方案：如果有多个userId和awardId相同的订单怎么办
         *  1.生成全局唯一id，放入消息中，每条消息唯一对应一个订单
         *  2.创建订单时保证一人一单
         */
        Long id = redisDao.nextId(String.valueOf(awardId));
        data.put("userId", userId);
        data.put("awardId", awardId);
        data.put("id", id);
        ObjectMapper objectMapper = new ObjectMapper();
        try {
            String json = objectMapper.writeValueAsString(data);
            return transactionService.sendTransaction(json, String.valueOf(UUID.randomUUID()));
        } catch (JsonProcessingException e) {
            throw new RuntimeException(e);
        }
    }

    public boolean check(Long userId, Long awardId){

        // 查询积分
        Integer currency = userCurrencyMapper.selectCurrency(userId);

        //查询奖品价格
        String awardConfigPriceKey = "award_config:price:" + awardId;
        Integer price = (Integer) redisDao.get(awardConfigPriceKey);

        //查询奖品截止日期
        String awardConfigEndTimeKey = "award_config:endTime:" + awardId;
        Date endTime = (Date) redisDao.get(awardConfigEndTimeKey);

        Integer count = idempotentMapper.select("userId:" + userId +"-awardId:" + awardId);

        // 检查积分是否充足、是否在活动期间内、是否已兑换过
        if(price > currency || new Date().after(endTime) || count != 0){
            return false;
        }

        return true;
    }





















    @Override
    public Result insert(Long userId, Long awardId) {
        int rows = userAwardMapper.insert(new UserAward(null, userId, awardId, 0, new Date()
                , new Date()));
        if(rows > 0)
            return Result.ok(null);
        else
            return Result.build(null, ResultCodeEnum.NOTLOGIN);
    }

    @Override
    public Result result(Long userId, Long awardId) {
        //从Redis中查询结果
        String resultKey = "user_award:" + userId + "-" + awardId;
        Integer status = (Integer)redisDao.hmGet(resultKey, "status");

        //从数据库查询结果
        if(status == null){
            status = userAwardMapper.selectStatus(userId, awardId);
        }

        //判断并返回
        if (status == null) {
            return Result.fail("You haven’t redeemed this award");
        } else {
            redisDao.hmSet(resultKey, "status", status);
            if(status == 0){
                return Result.build("Processing,please try again later.", ResultCodeEnum.Query_Later);
            }else if(status == 1){
                return Result.ok("Exchange successful.");
            }else{
                return Result.fail("Exchange failed.");
            }
        }
    }
}
