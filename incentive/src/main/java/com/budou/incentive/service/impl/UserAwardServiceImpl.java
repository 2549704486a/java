package com.budou.incentive.service.impl;

import com.budou.incentive.dao.mapper.*;
import com.budou.incentive.dao.model.*;
import com.budou.incentive.dao.redis.RedisDao;
import com.budou.incentive.service.*;
import com.budou.incentive.utils.*;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.github.benmanes.caffeine.cache.Cache;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.stereotype.Service;

import java.util.Date;
import java.util.HashMap;
import java.util.Map;
import java.util.UUID;

@Service
@Slf4j
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

    @Autowired
    private SeckillObservability seckillObservability;

    @Autowired
    private ObjectMapper objectMapper;

    @Override
    public Result<?> exchange(Long userId, Long awardId) {
        Result<?> validateResult = validateExchange(userId, awardId);
        if (validateResult != null) {
            return validateResult;
        }

        Map<String, Object> data = new HashMap<>();
        Long id = redisDao.nextId(String.valueOf(awardId));
        data.put("userId", userId);
        data.put("awardId", awardId);
        data.put("id", id);
        data.put("messageTimeMillis", System.currentTimeMillis());

        try {
            String json = objectMapper.writeValueAsString(data);
            Result<?> sendResult = transactionService.sendTransaction(json, String.valueOf(UUID.randomUUID()));
            if (sendResult != null && ResultCodeEnum.SUCCESS.getCode().equals(sendResult.getCode())) {
                seckillObservability.recordRequestAccepted(id, userId, awardId);
                return Result.build("Processing,please try again later.", ResultCodeEnum.Query_Later);
            }
            return sendResult;
        } catch (JsonProcessingException e) {
            log.warn("序列化事务消息失败, userId={}, awardId={}", userId, awardId, e);
            return Result.build(null, ResultCodeEnum.TRANSACTION_SEND_FAILED);
        }
    }

    private Result<?> validateExchange(Long userId, Long awardId) {
        if (userId == null || userId <= 0) {
            return Result.build(null, ResultCodeEnum.USERID_ERROR);
        }
        if (awardId == null || awardId <= 0) {
            return Result.build(null, ResultCodeEnum.AWARDID_ERROR);
        }

        Integer cachedStatus = getUserAwardStatus(userId, awardId);
        if (cachedStatus != null) {
            if (cachedStatus == 0) {
                return Result.build("Processing,please try again later.", ResultCodeEnum.Query_Later);
            }
            if (cachedStatus == 1) {
                return Result.build(null, ResultCodeEnum.AWARD_REDEEMED);
            }
        }

        Integer price = awardPriceCache.get(awardId, this::loadAwardPrice);
        if (price == null) {
            return Result.build(null, ResultCodeEnum.AWARDID_ERROR);
        }

        Date endTime = awardEndTimeCache.get(awardId, this::loadAwardEndTime);
        if (endTime == null) {
            return Result.build(null, ResultCodeEnum.AWARDID_ERROR);
        }

        Date now = new Date();
        if (now.after(endTime)) {
            return Result.build(null, ResultCodeEnum.AWARD_EXPIRE);
        }

        Integer inventory = loadAwardInventory(awardId);
        if (inventory == null || inventory <= 0) {
            return Result.build(null, ResultCodeEnum.Failed);
        }

        Integer currency = userCurrencyCache.get(userId, this::loadUserCurrency);
        if (currency == null) {
            return Result.build(null, ResultCodeEnum.USERID_ERROR);
        }

        if (currency < price) {
            return Result.build(null, ResultCodeEnum.INSUFFICIENT_CURRENCY);
        }

        String idempotentKey = buildIdempotentKey(userId, awardId);
        Integer cachedIdempotent = idempotentCache.getIfPresent(idempotentKey);
        if (cachedIdempotent != null && cachedIdempotent != 0) {
            return Result.build(null, ResultCodeEnum.AWARD_REDEEMED);
        }

        Integer count = idempotentMapper.select(idempotentKey);
        if (count != null && count != 0) {
            idempotentCache.put(idempotentKey, count);
            return Result.build(null, ResultCodeEnum.AWARD_REDEEMED);
        }

        return null;
    }

    private Integer loadUserCurrency(Long userId) {
        String userCurrencyKey = "user:currency:" + userId;
        Integer redisCurrency = (Integer) redisDao.get(userCurrencyKey);
        if (redisCurrency != null) {
            return redisCurrency;
        }
        Integer dbCurrency = userCurrencyMapper.selectCurrency(userId);
        if (dbCurrency != null) {
            redisDao.set(userCurrencyKey, dbCurrency);
        }
        return dbCurrency;
    }

    private Integer loadAwardPrice(Long awardId) {
        String awardConfigPriceKey = "award_config:price:" + awardId;
        Integer redisPrice = (Integer) redisDao.get(awardConfigPriceKey);
        if (redisPrice != null) {
            return redisPrice;
        }
        Integer dbPrice = awardConfigMapper.selectPrice(awardId);
        if (dbPrice != null) {
            redisDao.set(awardConfigPriceKey, dbPrice);
        }
        return dbPrice;
    }

    private Date loadAwardEndTime(Long awardId) {
        String awardConfigEndTimeKey = "award_config:endTime:" + awardId;
        Date redisEndTime = (Date) redisDao.get(awardConfigEndTimeKey);
        if (redisEndTime != null) {
            return redisEndTime;
        }
        Date dbEndTime = awardConfigMapper.selectEndTime(awardId);
        if (dbEndTime != null) {
            redisDao.set(awardConfigEndTimeKey, dbEndTime);
        }
        return dbEndTime;
    }

    private Integer loadAwardInventory(Long awardId) {
        String awardConfigInventoryKey = SeckillRedisKeys.buildAwardInventoryKey(awardId);
        Integer redisInventory = (Integer) redisDao.get(awardConfigInventoryKey);
        if (redisInventory != null) {
            return redisInventory;
        }
        Integer dbInventory = awardConfigMapper.selectInventory(awardId);
        if (dbInventory != null) {
            redisDao.set(awardConfigInventoryKey, dbInventory);
        }
        return dbInventory;
    }

    private Integer getUserAwardStatus(Long userId, Long awardId) {
        String statusKey = buildStatusKey(userId, awardId);
        Integer status = (Integer) redisDao.get(statusKey);
        if (status != null) {
            return status;
        }

        String legacyKey = "user_award:" + userId + "-" + awardId;
        status = (Integer) redisDao.hmGet(legacyKey, "status");
        if (status != null) {
            redisDao.set(statusKey, status);
        }
        return status;
    }

    private String buildStatusKey(Long userId, Long awardId) {
        return SeckillRedisKeys.buildStatusKey(userId, awardId);
    }

    private String buildIdempotentKey(Long userId, Long awardId) {
        return SeckillRedisKeys.buildIdempotentKey(userId, awardId);
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
        String statusKey = buildStatusKey(userId, awardId);
        Integer status = getUserAwardStatus(userId, awardId);
        if (status == null) {
            status = userAwardMapper.selectStatus(userId, awardId);
            if (status != null) {
                redisDao.set(statusKey, status);
            }
        }

        if (status == null) {
            return Result.fail("You haven鈥檛 redeemed this award");
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
