package com.budou.incentive.infra;

import com.budou.incentive.dao.mapper.AwardConfigMapper;
import com.budou.incentive.dao.mapper.UserAwardMapper;
import com.budou.incentive.dao.mapper.UserCurrencyMapper;
import com.budou.incentive.dao.model.UserAward;
import com.budou.incentive.dao.redis.RedisDao;
import com.budou.incentive.service.ConsumerService;
import com.budou.incentive.utils.SeckillObservability;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.github.benmanes.caffeine.cache.Cache;
import org.apache.rocketmq.client.consumer.listener.ConsumeConcurrentlyContext;
import org.apache.rocketmq.client.consumer.listener.ConsumeConcurrentlyStatus;
import org.apache.rocketmq.client.consumer.listener.MessageListenerConcurrently;
import org.apache.rocketmq.common.message.MessageExt;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.stereotype.Service;

import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Date;
import java.util.List;
import java.util.Map;
import java.util.Random;
import java.util.Set;
import java.util.UUID;

@Service
public class TransactionConsumer implements MessageListenerConcurrently {
    @Autowired
    private ConsumerService consumerService;
    @Autowired
    private UserAwardMapper userAwardMapper;
    @Autowired
    private AwardConfigMapper awardConfigMapper;
    @Autowired
    private RedisDao redisDao;
    @Autowired
    private UserCurrencyMapper userCurrencyMapper;
    @Autowired
    private SeckillObservability seckillObservability;

    @Autowired
    @Qualifier("awardPriceCache")
    private Cache<Long, Integer> awardPriceCache;

    @Autowired
    @Qualifier("awardIsOverSellCache")
    private Cache<Long, Integer> awardIsOverSellCache;

    @Override
    public ConsumeConcurrentlyStatus consumeMessage(List<MessageExt> msgs, ConsumeConcurrentlyContext context) {
        for (MessageExt msg : msgs) {
            Long userId = null;
            Long awardId = null;
            Long id = null;
            long requestStartMillis = msg.getBornTimestamp();
            try {
                ObjectMapper objectMapper = new ObjectMapper();
                Map<String, Object> data = objectMapper.readValue(
                        new String(msg.getBody(), StandardCharsets.UTF_8), Map.class);
                userId = Long.valueOf(String.valueOf(data.get("userId")));
                awardId = Long.valueOf(String.valueOf(data.get("awardId")));
                id = Long.valueOf(String.valueOf(data.get("id")));
                requestStartMillis = resolveRequestStartMillis(data, msg);

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
                System.out.println(price);
                if (price == null) {
                    seckillObservability.recordCompletion(id, userId, awardId, false,
                            elapsedSince(requestStartMillis), "price-not-found");
                    exchangeFail(id);
                    return ConsumeConcurrentlyStatus.CONSUME_SUCCESS;
                }

                Integer isOverSell = awardIsOverSellCache.get(awardId, key -> {
                    String awardConfigIsOverSellKey = "award_config:isOverSell:" + key;
                    Integer redisIsOverSell = (Integer) redisDao.get(awardConfigIsOverSellKey);
                    if (redisIsOverSell != null) {
                        return redisIsOverSell;
                    }
                    Integer dbIsOverSell = awardConfigMapper.selectIsOverSell(key);
                    if (dbIsOverSell != null) {
                        redisDao.set(awardConfigIsOverSellKey, dbIsOverSell);
                    }
                    return dbIsOverSell != null ? dbIsOverSell : 0;
                });

                if (isOverSell == 0) {
                    String awardInventorySplitKey = "award_inventory_split:" + awardId;
                    Long size = redisDao.getHashSize(awardInventorySplitKey);
                    System.out.println(size);
                    if (size == null || size == 0) {
                        seckillObservability.recordCompletion(id, userId, awardId, false,
                                elapsedSince(requestStartMillis), "split-size-empty");
                        exchangeFail(id);
                        return ConsumeConcurrentlyStatus.CONSUME_SUCCESS;
                    }

                    Set<String> keys = redisDao.getHashKeys(awardInventorySplitKey);
                    System.out.println(keys);
                    if (keys == null || keys.isEmpty()) {
                        seckillObservability.recordCompletion(id, userId, awardId, false,
                                elapsedSince(requestStartMillis), "split-keys-empty");
                        exchangeFail(id);
                        return ConsumeConcurrentlyStatus.CONSUME_SUCCESS;
                    }
                    ArrayList<String> keyList = new ArrayList<>(keys);
                    Random rand = new Random();
                    String hashKey = keyList.get(rand.nextInt(keyList.size()));
                    String lockKey = "inventoryLock:award:" + awardId + ":split:" + hashKey;
                    String lockValue = UUID.randomUUID().toString();

                    boolean locked = Boolean.TRUE.equals(redisDao.setnx(lockKey, lockValue, 10L));
                    if (!locked) {
                        seckillObservability.recordLockFail(id, userId, awardId, hashKey);
                        seckillObservability.recordReconsumeLater(id, userId, awardId, "lock-failed");
                        return ConsumeConcurrentlyStatus.RECONSUME_LATER;
                    }

                    try {
                        Integer splitInventory = (Integer) redisDao.hmGet(awardInventorySplitKey, hashKey);
                        if (splitInventory == null || splitInventory <= 0) {
                            redisDao.hmDel(awardInventorySplitKey, hashKey);
                            Long leftSize = redisDao.getHashSize(awardInventorySplitKey);
                            System.out.println(leftSize);
                            if (leftSize == null || leftSize == 0) {
                                seckillObservability.recordCompletion(id, userId, awardId, false,
                                        elapsedSince(requestStartMillis), "split-inventory-empty");
                                exchangeFail(id);
                                return ConsumeConcurrentlyStatus.CONSUME_SUCCESS;
                            }
                            seckillObservability.recordReconsumeLater(id, userId, awardId, "split-empty-retry");
                            return ConsumeConcurrentlyStatus.RECONSUME_LATER;
                        }

                        try {
                            consumerService.update1(
                                    id,
                                    userId,
                                    awardId,
                                    price,
                                    Long.valueOf(hashKey.substring(hashKey.indexOf(":") + 1))
                            );
                            seckillObservability.recordCompletion(id, userId, awardId, true,
                                    elapsedSince(requestStartMillis), "consume-success");
                        } catch (Exception e) {
                            System.out.println("update1 exception: " + e.getMessage());
                            seckillObservability.recordCompletion(id, userId, awardId, false,
                                    elapsedSince(requestStartMillis), "update1-exception");
                            exchangeFail(id);
                            return ConsumeConcurrentlyStatus.CONSUME_SUCCESS;
                        }
                    } finally {
                        redisDao.remove(lockKey);
                    }
                } else {
                    try {
                        consumerService.update2(id, userId, awardId, price);

                        String awardConfigInventoryKey = "award_config:inventory:" + awardId;
                        redisDao.decrement(awardConfigInventoryKey);
                        seckillObservability.recordCompletion(id, userId, awardId, true,
                                elapsedSince(requestStartMillis), "consume-success-over-sell");
                    } catch (Exception e) {
                        userAwardMapper.updateStatusFail(id);
                        seckillObservability.recordCompletion(id, userId, awardId, false,
                                elapsedSince(requestStartMillis), "update2-exception");
                    }
                }
            } catch (Exception e) {
                seckillObservability.recordReconsumeLater(id, userId, awardId,
                        "consume-exception:" + e.getClass().getSimpleName());
                return ConsumeConcurrentlyStatus.RECONSUME_LATER;
            }
        }

        return ConsumeConcurrentlyStatus.CONSUME_SUCCESS;
    }

    private void exchangeFail(Long id) {
        UserAward userAward = new UserAward();
        userAward.setId(id);
        userAward.setUpdateTime(new Date());
        userAward.setStatus(-1);
        userAwardMapper.updateStatus(userAward);
    }

    private long resolveRequestStartMillis(Map<String, Object> data, MessageExt msg) {
        Object requestTimeMillis = data.get("requestTimeMillis");
        if (requestTimeMillis == null) {
            return msg.getBornTimestamp();
        }
        try {
            return Long.parseLong(String.valueOf(requestTimeMillis));
        } catch (NumberFormatException ex) {
            return msg.getBornTimestamp();
        }
    }

    private long elapsedSince(long startMillis) {
        return Math.max(System.currentTimeMillis() - startMillis, 0L);
    }
}
