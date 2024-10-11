package com.budou.incentive.infra;

import com.budou.incentive.dao.mapper.AwardInventorySplitMapper;
import com.budou.incentive.dao.mapper.AwardConfigMapper;
import com.budou.incentive.dao.mapper.UserAwardMapper;
import com.budou.incentive.dao.mapper.UserCurrencyMapper;
import com.budou.incentive.dao.model.AwardConfig;
import com.budou.incentive.dao.model.AwardInventorySplit;
import com.budou.incentive.dao.model.UserAward;
import com.budou.incentive.dao.model.UserCurrency;
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
    private UserCurrencyMapper userCurrencyMapper;
    @Autowired
    private AwardConfigMapper awardConfigMapper;
    @Autowired
    private RedisDao redisDao;
    @Autowired
    private AwardInventorySplitMapper awardInventorySplitMapper;
    @Autowired
    private RedisLockWithRenewal redisLockWithRenewal;

    @Override
    //ConsumeConcurrentlyContext：1获取当前消费的队列信息2设置消息重试延迟3帮助处理并发消费时的重试策略与消息状态管理。
    public ConsumeConcurrentlyStatus consumeMessage(List<MessageExt> msgs, ConsumeConcurrentlyContext context) {
        try{
            for (MessageExt msg : msgs) {
                System.out.println("TransactionConsumer.consumeMessage:开始消费消息...");
                System.out.println("Received message: " + new String(msg.getBody()));

                System.out.println("TransactionConsumer.consumeMessage:开始解析消息...");
                //从msg中获取userId和awardId
                ObjectMapper objectMapper = new ObjectMapper();
                Map data;
                try {
                    data = objectMapper.readValue(new String(msg.getBody(), StandardCharsets.UTF_8), Map.class);
                } catch (Exception e) {
                    throw new RuntimeException(e);
                }
                Long userId = Long.valueOf(String.valueOf(data.get("userId")));
                Long awardId = Long.valueOf(String.valueOf(data.get("awardId")));

                System.out.println("TransactionConsumer.consumeMessage:从redis、数据库查询相关信息...");
                //从redis、mysql查询商品的price、inventory、isOverSell
                String awardConfigPriceKey = "award_config:price:" + awardId;
                Integer price = (Integer) redisDao.get(awardConfigPriceKey);
                System.out.println("1");
                if(price == null){
                    price = awardConfigMapper.selectPrice(awardId);
                    redisDao.set(awardConfigPriceKey, price);
                }
                System.out.println("2");
                String awardConfigInventoryKey = "award_config:inventory:" + awardId;
                Integer inventory = (Integer) redisDao.get(awardConfigInventoryKey);
                System.out.println("3");
                if(inventory == null){
                    inventory = awardConfigMapper.selectInventory(awardId);
                    redisDao.set(awardConfigInventoryKey, inventory);
                }
                System.out.println("4");
                String awardConfigIsOverSellKey = "award_config:isOverSell:" + awardId;
                Integer isOverSell = (Integer) redisDao.get(awardConfigIsOverSellKey);
                System.out.println("5");
                if(isOverSell == null){
                    isOverSell = awardConfigMapper.selectIsOverSell(awardId);
                    redisDao.set(awardConfigIsOverSellKey, isOverSell);
                }
                System.out.println("6");
                //从redis、mysql查询userAward的status
                String userAwardStatusKey = "user_award:status:" + userId + ":" + awardId;
                Integer status = (Integer) redisDao.get(userAwardStatusKey);
                System.out.println("7");
                if(status == null){
                    status = userAwardMapper.selectStatus(userId, awardId);
                    redisDao.set(userAwardStatusKey, status);
                }
                System.out.println("8");
                //从redis、mysql查询user_currency的currency
                String userCurrencyKey = "user_currency:" + userId;
                Integer currency = (Integer) redisDao.get(userCurrencyKey);
                System.out.println("9");
                if(currency == null){
                    currency = userCurrencyMapper.selectCurrency(userId);
                    redisDao.set(userCurrencyKey, currency);
                }

                System.out.println("TransactionConsumer.consumeMessage:检查是否重复消费...");
                //检查奖品是否已处理，避免重复消费
                if(status != 0){
                    System.out.println("TransactionConsumer.consumeMessage:该消息是重复消息");
                    return ConsumeConcurrentlyStatus.CONSUME_SUCCESS;
                }

                //判断库存
                if(inventory > 0){
                    if(isOverSell == 0) {
                        System.out.println("TransactionConsumer.consumeMessage:兑换不可超卖商品...");
                        //查询所有库存记录
                        //是否需要将redis中库存为0的库存记录删除？
                        String awardInventorySplitKey = "award_inventory_split:" + awardId;
                        List<AwardInventorySplit> awardInventorySplitList = new ArrayList<>();
                        List<Object> list = redisDao.lRange(awardInventorySplitKey,0, -1);
                        if(list.size() == 0){
                            awardInventorySplitList = awardInventorySplitMapper.select(awardId);
                            for(AwardInventorySplit item : awardInventorySplitList){
                                redisDao.lPush(awardInventorySplitKey, item);
                            }
                        }else {
                            for(Object item : list){
                                awardInventorySplitList.add((AwardInventorySplit) item);
                            }
                        }

                        //随机选择一个库存记录，加锁
                        System.out.println("TransactionConsumer.consumeMessage:随机选择库存记录");
                        Random rand = new Random();
                        int randomIndex = rand.nextInt(awardInventorySplitList.size());
                        AwardInventorySplit awardInventorySplit = awardInventorySplitList.get(randomIndex);
                        String lockKey = "inventoryLock:"  + awardId + awardInventorySplit.getId() + "-";
                        String lockValue = msg.getTransactionId();
                        System.out.println("TransactionConsumer.consumeMessage:加锁中...");
                        Long token = redisLockWithRenewal.acquireLock(lockKey, lockValue);
                        if(token == null){
                            return ConsumeConcurrentlyStatus.RECONSUME_LATER;
                        }

                        //扣减库存
                        AwardConfig awardConfig = new AwardConfig();
                        awardConfig.setAwardId(awardId);
                        awardConfig.setInventory(inventory - 1);

                        //扣减分库存
                        awardInventorySplit.setInventory(awardInventorySplit.getInventory() - 1);

                        //扣减积分
                        UserCurrency userCurrency = new UserCurrency();
                        userCurrency.setUserId(userId);
                        userCurrency.setCurrency(currency - price);

                        //更新商品的兑换状态
                        UserAward userAward = new UserAward();
                        userAward.setUserId(userId);
                        userAward.setAwardId(awardId);
                        userAward.setUpdateTime(new Date());
                        userAward.setStatus(1);//status=1表示兑换成功

//                        redisLockWithRenewal.isLatestToken(token);
                        consumerService.update1(awardConfig, awardInventorySplit, userCurrency, userAward,
                                lockKey, lockValue, token);
//                        redisLockWithRenewal.releaseLock(lockKey, lockValue);
                    } else {
                        System.out.println("TransactionConsumer.consumeMessage:兑换可超卖商品...");
                        //扣减积分  会不会出现：用户同时兑换了多个商品，当若干商品处理完成后，这里没有足够的积分了？
                        UserCurrency userCurrency = new UserCurrency();
                        userCurrency.setUserId(userId);
                        userCurrency.setCurrency(currency - price);

                        //更新商品的兑换状态
                        UserAward userAward = new UserAward();
                        userAward.setUserId(userId);
                        userAward.setAwardId(awardId);
                        userAward.setUpdateTime(new Date());
                        userAward.setStatus(1);//status=1表示兑换成功

                        //执行事务
                        consumerService.update2(userCurrency, userAward);

                        //扣减库存
                        redisDao.set(awardConfigInventoryKey, inventory - 1);
                        System.out.println("TransactionConsumer.consumeMessage:兑换成功");
                    }
                }else {
                    //更新数据库
                    UserAward userAward = new UserAward();
                    userAward.setUserId(userId);
                    userAward.setAwardId(awardId);
                    userAward.setUpdateTime(new Date());
                    userAward.setStatus(-1);//status=-1表示兑换失败
                    userAwardMapper.updateStatus(userAward);
                    System.out.println("TransactionConsumer.consumeMessage:兑换失败");
                }
            }
        }catch (Exception e){
            System.out.println(e);
        }
        //返回 ConsumeConcurrentlyStatus.CONSUME_SUCCESS，表示消息消费成功。
        return ConsumeConcurrentlyStatus.CONSUME_SUCCESS;
    }
}