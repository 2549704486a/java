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
import java.util.Comparator;
import java.util.Date;
import java.util.List;
import java.util.Map;
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
                    if (size == null || size == 0) {
                        seckillObservability.recordCompletion(id, userId, awardId, false,
                                elapsedSince(requestStartMillis), "split-size-empty");
                        exchangeFail(id);
                        return ConsumeConcurrentlyStatus.CONSUME_SUCCESS;
                    }

                    Set<String> keys = redisDao.getHashKeys(awardInventorySplitKey);
                    if (keys == null || keys.isEmpty()) {
                        seckillObservability.recordCompletion(id, userId, awardId, false,
                                elapsedSince(requestStartMillis), "split-keys-empty");
                        exchangeFail(id);
                        return ConsumeConcurrentlyStatus.CONSUME_SUCCESS;
                    }
                    ArrayList<String> keyList = new ArrayList<>(keys);
                    keyList.sort(Comparator.comparingLong(this::extractSplitId));

                    int preferredIndex = preferredSplitIndex(id, keyList.size());
                    boolean encounteredLockConflict = false;

                    for (int offset = 0; offset < keyList.size(); offset++) {
                        String hashKey = keyList.get((preferredIndex + offset) % keyList.size());
                        String lockKey = "inventoryLock:award:" + awardId + ":split:" + hashKey;
                        String lockValue = UUID.randomUUID().toString();

                        boolean locked = Boolean.TRUE.equals(redisDao.setnx(lockKey, lockValue, 10L));
                        if (!locked) {
                            encounteredLockConflict = true;
                            seckillObservability.recordLockFail(id, userId, awardId, hashKey);
                            continue;
                        }

                        try {
                            Integer splitInventory = (Integer) redisDao.hmGet(awardInventorySplitKey, hashKey);
                            if (splitInventory == null || splitInventory <= 0) {
                                redisDao.hmDel(awardInventorySplitKey, hashKey);
                                continue;
                            }

                            try {
                                consumerService.update1(
                                        id,
                                        userId,
                                        awardId,
                                        price,
                                        extractSplitId(hashKey)
                                );
                                seckillObservability.recordCompletion(id, userId, awardId, true,
                                        elapsedSince(requestStartMillis), "consume-success");
                                return ConsumeConcurrentlyStatus.CONSUME_SUCCESS;
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
                    }

                    Long leftSize = redisDao.getHashSize(awardInventorySplitKey);
                    if (leftSize == null || leftSize == 0) {
                        seckillObservability.recordCompletion(id, userId, awardId, false,
                                elapsedSince(requestStartMillis), "split-inventory-empty");
                        exchangeFail(id);
                        return ConsumeConcurrentlyStatus.CONSUME_SUCCESS;
                    }

                    seckillObservability.recordReconsumeLater(
                            id,
                            userId,
                            awardId,
                            encounteredLockConflict ? "all-splits-locked" : "no-split-available"
                    );
                    return ConsumeConcurrentlyStatus.RECONSUME_LATER;
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

    private int preferredSplitIndex(Long orderId, int splitCount) {
        if (splitCount <= 0) {
            return 0;
        }
        return Math.floorMod(Long.hashCode(orderId), splitCount);
    }

    private long extractSplitId(String hashKey) {
        int separator = hashKey.indexOf(':');
        if (separator < 0 || separator == hashKey.length() - 1) {
            throw new IllegalArgumentException("Unexpected split key: " + hashKey);
        }
        return Long.parseLong(hashKey.substring(separator + 1));
    }
}
