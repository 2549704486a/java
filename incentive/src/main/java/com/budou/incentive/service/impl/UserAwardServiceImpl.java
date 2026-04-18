package com.budou.incentive.service.impl;

import com.budou.incentive.dao.mapper.*;
import com.budou.incentive.dao.model.*;
import com.budou.incentive.dao.redis.RedisDao;
import com.budou.incentive.service.*;
import com.budou.incentive.utils.*;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.github.benmanes.caffeine.cache.Cache;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Qualifier;
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

    @Autowired
    private AwardConfigMapper awardConfigMapper;

    // Qualifier 注解用于指定注入哪个 Bean，这里是为了区分不同类型的 Cache Bean。
    @Autowired
    @Qualifier("awardPriceCache")
    private Cache<Long, Integer> awardPriceCache;

    @Autowired
    @Qualifier("awardEndTimeCache")
    private Cache<Long, Date> awardEndTimeCache;

    @Autowired
    @Qualifier("userCurrencyCache")
    private Cache<Long, Integer> userCurrencyCache;

    @Autowired
    @Qualifier("idempotentCache")
    private Cache<String, Integer> idempotentCache;

    @Override
    public Result<?> exchange(Long userId, Long awardId) {
        System.out.println("UserAwardServiceImpl.exchange: exchange, userId = " + userId + " awardId = " + awardId);

        // 参数及业务前置校验，返回更明确的错误码
        Result<?> validateResult = validateExchange(userId, awardId);
        if (validateResult != null) {
            return validateResult;
        }

        // 发送事务消息（异步处理扣积分与扣库存）
        Map<String, Object> data = new HashMap<>();

        // 生成全局唯一订单 id，保证一人多单也可以区分
        Long id = redisDao.nextId(String.valueOf(awardId));
        data.put("userId", userId);
        data.put("awardId", awardId);
        data.put("id", id);

        ObjectMapper objectMapper = new ObjectMapper();
        try {
            String json = objectMapper.writeValueAsString(data);
            Result<?> sendResult = transactionService.sendTransaction(json, String.valueOf(UUID.randomUUID()));

            // 发送成功时，返回“稍后查询结果”的提示，使接口语义更贴近异步兑换
            if (sendResult != null && ResultCodeEnum.SUCCESS.getCode().equals(sendResult.getCode())) {
                return Result.build("Processing,please try again later.", ResultCodeEnum.Query_Later);
            }
            return sendResult;
        } catch (JsonProcessingException e) {
            return Result.build(null, ResultCodeEnum.TRANSACTION_SEND_FAILED);
        }
    }

    /**
     * 兑换前置校验：参数、用户、奖品信息、积分是否足够、是否重复兑换等
     * 返回非 null 表示校验失败并给出具体错误码；返回 null 表示校验通过。
     */
    private Result<?> validateExchange(Long userId, Long awardId) {
        if (userId == null || userId <= 0) {
            return Result.build(null, ResultCodeEnum.USERID_ERROR);
        }
        if (awardId == null || awardId <= 0) {
            return Result.build(null, ResultCodeEnum.AWARDID_ERROR);
        }

        Integer currency = userCurrencyCache.get(userId, key -> {
            String userCurrencyKey = "user:currency:" + key;
            Integer redisCurrency = (Integer) redisDao.get(userCurrencyKey);
            if (redisCurrency != null) {
                return redisCurrency;
            }
            Integer dbCurrency = userCurrencyMapper.selectCurrency(key);
            if (dbCurrency != null) {
                redisDao.set(userCurrencyKey, dbCurrency);
            }
            return dbCurrency;
        });
        if (currency == null) {
            return Result.build(null, ResultCodeEnum.USERID_ERROR);
        }

        Integer price = awardPriceCache.get(awardId, key -> {
            String awardConfigPriceKey = "award_config:price:" + key;
            Integer redisPrice = (Integer) redisDao.get(awardConfigPriceKey);
            if (redisPrice != null) {
                return redisPrice;
            }
            Integer dbPrice = awardConfigMapper.selectPrice(key);
            if (dbPrice != null) {
                redisDao.set(awardConfigPriceKey, dbPrice);
            }
            return dbPrice;
        });
        if (price == null) {
            return Result.build(null, ResultCodeEnum.AWARDID_ERROR);
        }

        Date endTime = awardEndTimeCache.get(awardId, key -> {
            String awardConfigEndTimeKey = "award_config:endTime:" + key;
            Date redisEndTime = (Date) redisDao.get(awardConfigEndTimeKey);
            if (redisEndTime != null) {
                return redisEndTime;
            }
            Date dbEndTime = awardConfigMapper.selectEndTime(key);
            if (dbEndTime != null) {
                redisDao.set(awardConfigEndTimeKey, dbEndTime);
            }
            return dbEndTime;
        });
        if (endTime == null) {
            return Result.build(null, ResultCodeEnum.AWARDID_ERROR);
        }

        String awardInventorySplitKey = "award_inventory_split:" + awardId;
        Long size = redisDao.getHashSize(awardInventorySplitKey);
        if (size == null || size == 0) {
            return Result.build(null, ResultCodeEnum.Failed);
        }

        Date now = new Date();
        if (now.after(endTime)) {
            return Result.build(null, ResultCodeEnum.AWARD_EXPIRE);
        }

        if (currency < price) {
            return Result.build(null, ResultCodeEnum.INSUFFICIENT_CURRENCY);
        }

        String idempotentKey = "userId:" + userId + "-awardId:" + awardId;
        Integer count = idempotentCache.get(idempotentKey, key -> {
            Integer dbCount = idempotentMapper.select(key);
            return dbCount != null ? dbCount : 0;
        });
        if (count != null && count != 0) {
            return Result.build(null, ResultCodeEnum.AWARD_REDEEMED);
        }

        return null;
    }

    @Override
    public Result<?> insert(Long userId, Long awardId) {
        int rows = userAwardMapper.insert(new UserAward(null, userId, awardId, 0, new Date()
                , new Date()));
        if(rows > 0)
            return Result.ok(null);
        else
            return Result.build(null, ResultCodeEnum.NOTLOGIN);
    }

    @Override
    public Result<?> result(Long userId, Long awardId) {
        // 统一使用 string 类型的状态键
        String statusKey = "user_award:status:" + userId + ":" + awardId;
        Integer status = (Integer) redisDao.get(statusKey);

        // 兼容历史 hash 结构的 key（老版本写在 user_award:{userId}-{awardId} 里）
        if (status == null) {
            String legacyKey = "user_award:" + userId + "-" + awardId;
            status = (Integer) redisDao.hmGet(legacyKey, "status");
        }

        // 从数据库查询结果并回填缓存
        if (status == null) {
            status = userAwardMapper.selectStatus(userId, awardId);
            if (status != null) {
                redisDao.set(statusKey, status);
            }
        }

        // 判断并返回
        if (status == null) {
            return Result.fail("You haven’t redeemed this award");
        }

        if (status == 0) {
            return Result.build("Processing,please try again later.", ResultCodeEnum.Query_Later);
        } else if (status == 1) {
            return Result.ok("Exchange successful.");
        } else {
            return Result.fail("Exchange failed.");
        }
    }
}
