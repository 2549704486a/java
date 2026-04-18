package com.budou.incentive.infra;

import com.budou.incentive.dao.mapper.AwardConfigMapper;
import com.budou.incentive.dao.mapper.UserAwardMapper;
import com.budou.incentive.dao.mapper.UserCurrencyMapper;
import com.budou.incentive.dao.model.UserAward;
import com.budou.incentive.dao.redis.RedisDao;
import com.budou.incentive.service.ConsumerService;
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
import java.util.*;

@Service
//类实现了 MessageListenerConcurrently 接口，该接口用于处理并发消费的消息。
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
    @Qualifier("awardPriceCache")
    private Cache<Long, Integer> awardPriceCache;

    @Autowired
    @Qualifier("awardIsOverSellCache")
    private Cache<Long, Integer> awardIsOverSellCache;

    @Override
    public ConsumeConcurrentlyStatus consumeMessage(List<MessageExt> msgs, ConsumeConcurrentlyContext context) {
        for (MessageExt msg : msgs) {
            try {
                ObjectMapper objectMapper = new ObjectMapper();
                Map<String, Object> data = objectMapper.readValue(
                        new String(msg.getBody(), StandardCharsets.UTF_8), Map.class);
                Long userId = Long.valueOf(String.valueOf(data.get("userId")));
                Long awardId = Long.valueOf(String.valueOf(data.get("awardId")));
                Long id = Long.valueOf(String.valueOf(data.get("id")));

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
                        exchangeFail(id);
                        return ConsumeConcurrentlyStatus.CONSUME_SUCCESS;
                    }

                    Set<String> keys = redisDao.getHashKeys(awardInventorySplitKey);
                    System.out.println(keys);
                    if (keys == null || keys.isEmpty()) {
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
                        return ConsumeConcurrentlyStatus.RECONSUME_LATER;
                    }

                    try {
                        Integer splitInventory = (Integer) redisDao.hmGet(awardInventorySplitKey, hashKey);
                        if (splitInventory == null || splitInventory <= 0) {
                            redisDao.hmDel(awardInventorySplitKey, hashKey);
                            Long leftSize = redisDao.getHashSize(awardInventorySplitKey);
                            System.out.println(leftSize);
                            if (leftSize == null || leftSize == 0) {
                                exchangeFail(id);
                                return ConsumeConcurrentlyStatus.CONSUME_SUCCESS;
                            }
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
                        } catch (Exception e) {
                            System.out.println("update1 exception: " + e.getMessage());
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
                    } catch (Exception e) {
                        userAwardMapper.updateStatusFail(id);
                    }
                }
            } catch (Exception e) {
                return ConsumeConcurrentlyStatus.RECONSUME_LATER;
            }
        }

        return ConsumeConcurrentlyStatus.CONSUME_SUCCESS;
    }

    private void exchangeFail(Long id) {
        //更新数据库
        UserAward userAward = new UserAward();
        userAward.setId(id);
        userAward.setUpdateTime(new Date());
        userAward.setStatus(-1);//status=-1表示兑换失败
        userAwardMapper.updateStatus(userAward);
    }
}