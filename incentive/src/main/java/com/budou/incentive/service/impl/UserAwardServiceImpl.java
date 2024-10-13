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
    private AwardConfigMapper awardConfigMapper;

    @Autowired
    private UserCurrencyMapper userCurrencyMapper;

    @Autowired
    private RedisDao redisDao;

    @Override
    public Result exchange(Long userId, Long awardId) {
        System.out.println("UserAwardServiceImpl.exchange: exchange, userId = " + userId + "awardId = " + awardId);
        System.out.println("UserAwardServiceImpl.exchange: 正在查询数据库： user&award...");

        //查询用户积分
        String userCurrencyKey = "user_currency:" + userId;
        Integer currency = (Integer) redisDao.get(userCurrencyKey);
        if(currency == null){
            currency = userCurrencyMapper.selectCurrency(userId);
            redisDao.set(userCurrencyKey, currency);
        }

        //查询奖品价格
        String awardConfigPriceKey = "award_config:price:" + awardId;
        Integer price = (Integer) redisDao.get(awardConfigPriceKey);
        if(price == null){
            price = awardConfigMapper.selectPrice(awardId);
            redisDao.set(awardConfigPriceKey, price);
        }

        //查询奖品截止日期
        String awardConfigEndTimeKey = "award_config:endTime:" + awardId;
        Date endTime = (Date) redisDao.get(awardConfigEndTimeKey);
        if (endTime == null) {
            endTime = awardConfigMapper.selectEndTime(awardId);
            redisDao.set(awardConfigEndTimeKey, endTime);
        }

        //确认奖品是否在有效期内
        System.out.println("UserAwardServiceImpl.exchange: 正在确认奖品有效期");
        if(new Date().after(endTime)){
            return Result.build(null, ResultCodeEnum.AWARD_EXPIRE);
        }

        System.out.println("UserAwardServiceImpl.exchange: 正在确认用户是否兑换过奖品");
        //查询用户是否兑换过该奖品   用户兑换过一次，无论成功或失败都不能再次兑换？还是说失败了还可以再次发送兑换请求？
        String userAwardStatusKey = "user_award:status:" + userId +":" + awardId;
        Integer status = (Integer) redisDao.get(userAwardStatusKey);
        if(status == null){
            status = userAwardMapper.selectStatus(userId, awardId);
            if(status != null){
                redisDao.set(userAwardStatusKey, status);
                if(status == 0 || status == 1){
                    System.out.println("UserAwardServiceImpl.exchange: 用户已兑换过奖品,请查询处理结果");
                    return Result.build(null, ResultCodeEnum.AWARD_REDEEMED);
                }else{
                    redisDao.remove(userAwardStatusKey);
                    Integer rows = userAwardMapper.delete(userId, awardId);
                    System.out.println(rows);
                }
            }
        }else{
            if(status == 0 || status == 1){
                System.out.println("UserAwardServiceImpl.exchange: 用户已兑换过奖品,请查询处理结果");
                return Result.build(null, ResultCodeEnum.AWARD_REDEEMED);
            }else {
                redisDao.remove(userAwardStatusKey);
                Integer rows = userAwardMapper.delete(userId, awardId);
                System.out.println(rows);
            }
        }

        System.out.println("UserAwardServiceImpl.exchange: 正在检查积分是否足够");
        //检查积分是否足够
        if(currency < price){
            return Result.build(null, ResultCodeEnum.INSUFFICIENT_CURRENCY);
        }

        System.out.println("UserAwardServiceImpl.exchange: 正在准备事务消息...");
        //发送事务消息
        Map<String, Object> data = new HashMap<>();
        data.put("userId", userId);
        data.put("awardId", awardId);
        ObjectMapper objectMapper = new ObjectMapper();
        try {
            String json = objectMapper.writeValueAsString(data);
            return transactionService.sendTransaction(json, String.valueOf(UUID.randomUUID()));
        } catch (JsonProcessingException e) {
            throw new RuntimeException(e);
        }
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
