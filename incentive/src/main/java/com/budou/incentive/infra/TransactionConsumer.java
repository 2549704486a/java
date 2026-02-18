package com.budou.incentive.infra;

import com.budou.incentive.dao.mapper.AwardConfigMapper;
import com.budou.incentive.dao.mapper.UserAwardMapper;
import com.budou.incentive.dao.mapper.UserCurrencyMapper;
import com.budou.incentive.dao.model.UserAward;
import com.budou.incentive.dao.redis.RedisDao;
import com.budou.incentive.service.ConsumerService;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.apache.rocketmq.client.consumer.listener.ConsumeConcurrentlyContext;
import org.apache.rocketmq.client.consumer.listener.ConsumeConcurrentlyStatus;
import org.apache.rocketmq.client.consumer.listener.MessageListenerConcurrently;
import org.apache.rocketmq.common.message.MessageExt;
import org.springframework.beans.factory.annotation.Autowired;
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

    @Override
    //ConsumeConcurrentlyContext：1获取当前消费的队列信息2设置消息重试延迟3帮助处理并发消费时的重试策略与消息状态管理。
    public ConsumeConcurrentlyStatus consumeMessage(List<MessageExt> msgs, ConsumeConcurrentlyContext context) {
        for (MessageExt msg : msgs) {
            try {
                // 解析数据
                ObjectMapper objectMapper = new ObjectMapper();
                Map<String, Object> data = objectMapper.readValue(
                        new String(msg.getBody(), StandardCharsets.UTF_8), Map.class);
                Long userId = Long.valueOf(String.valueOf(data.get("userId")));
                Long awardId = Long.valueOf(String.valueOf(data.get("awardId")));
                Long id = Long.valueOf(String.valueOf(data.get("id")));

                // 从 redis、mysql 查询商品的 price、isOverSell，带有兜底与缓存回写
                String awardConfigPriceKey = "award_config:price:" + awardId;
                Integer price = (Integer) redisDao.get(awardConfigPriceKey);
                if (price == null) {
                    price = awardConfigMapper.selectPrice(awardId);
                    if (price != null) {
                        redisDao.set(awardConfigPriceKey, price);
                    } else {
                        exchangeFail(id);
                        return ConsumeConcurrentlyStatus.CONSUME_SUCCESS;
                    }
                }

                String awardConfigIsOverSellKey = "award_config:isOverSell:" + awardId;
                Integer isOverSell = (Integer) redisDao.get(awardConfigIsOverSellKey);
                if (isOverSell == null) {
                    isOverSell = awardConfigMapper.selectIsOverSell(awardId);
                    if (isOverSell != null) {
                        redisDao.set(awardConfigIsOverSellKey, isOverSell);
                    } else {
                        // 默认视为不允许超卖，更安全
                        isOverSell = 0;
                    }
                }

                if (isOverSell == 0) {
                    // 不允许超卖：使用分片库存
                    String awardInventorySplitKey = "award_inventory_split:" + awardId;
                    Long size = redisDao.getHashSize(awardInventorySplitKey);
                    if (size == null || size == 0) {
                        exchangeFail(id);
                        return ConsumeConcurrentlyStatus.CONSUME_SUCCESS;
                    }

                    // 随机选择分片，加锁
                    Set<String> keys = redisDao.getHashKeys(awardInventorySplitKey);
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
                        // 检查该分片是否有余量
                        Integer splitInventory = (Integer) redisDao.hmGet(awardInventorySplitKey, hashKey);
                        if (splitInventory == null || splitInventory <= 0) {
                            redisDao.hmDel(awardInventorySplitKey, hashKey);
                            Long leftSize = redisDao.getHashSize(awardInventorySplitKey);
                            if (leftSize == null || leftSize == 0) {
                                // 所有分片都没有库存了，直接标记失败，避免无限重试
                                exchangeFail(id);
                                return ConsumeConcurrentlyStatus.CONSUME_SUCCESS;
                            }
                            // 还有其他分片有库存，稍后重试
                            return ConsumeConcurrentlyStatus.RECONSUME_LATER;
                        }

                        // 更新数据库
                        try {
                            consumerService.update1(
                                    id,
                                    userId,
                                    awardId,
                                    price,
                                    Long.valueOf(hashKey.substring(hashKey.indexOf(":") + 1))
                            );
                        } catch (Exception e) {
                            exchangeFail(id);
                            return ConsumeConcurrentlyStatus.CONSUME_SUCCESS;
                        }
                    } finally {
                        redisDao.remove(lockKey);
                    }
                } else {
                    // 允许超卖：仅做积分扣减 + 状态更新，库存由全局库存键控制
                    try {
                        consumerService.update2(id, userId, awardId, price);

                        // 扣减库存，update2 成功了，就扣减库存，无论 decrement 是否成功，都算兑换成功
                        String awardConfigInventoryKey = "award_config:inventory:" + awardId;
                        redisDao.decrement(awardConfigInventoryKey);
                    } catch (Exception e) {
                        userAwardMapper.updateStatusFail(id);
                    }
                }
            } catch (Exception e) {
                // 解析或业务异常，适度重试
                return ConsumeConcurrentlyStatus.RECONSUME_LATER;
            }
        }

        //返回 ConsumeConcurrentlyStatus.CONSUME_SUCCESS，表示消息消费成功。
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