package com.budou.incentive.infra;

import com.budou.incentive.dao.mapper.AwardInventorySplitMapper;
import com.budou.incentive.dao.mapper.AwardConfigMapper;
import com.budou.incentive.dao.mapper.UserAwardMapper;
import com.budou.incentive.dao.mapper.UserCurrencyMapper;
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


                System.out.println("TransactionConsumer.consumeMessage"+"(" + userId + ")" +
                        ":从redis、数据库查询相关信息...");
                //从redis、mysql查询商品的price、inventory、isOverSell
                String awardConfigPriceKey = "award_config:price:" + awardId;
                Integer price = (Integer) redisDao.get(awardConfigPriceKey);
                if(price == null){
                    price = awardConfigMapper.selectPrice(awardId);
                    redisDao.set(awardConfigPriceKey, price);
                }

                String awardConfigIsOverSellKey = "award_config:isOverSell:" + awardId;
                Integer isOverSell = (Integer) redisDao.get(awardConfigIsOverSellKey);
                if(isOverSell == null){
                    isOverSell = awardConfigMapper.selectIsOverSell(awardId);
                    redisDao.set(awardConfigIsOverSellKey, isOverSell);
                }

                //redis查询inventory，若无，则初始化，超卖品直接获取，非超卖商品总库存由各个分库存相加得到
                String awardConfigInventoryKey = "award_config:inventory:" + awardId;
                Integer inventory = (Integer) redisDao.get(awardConfigInventoryKey);
                if(inventory == null){
                    //初始化inventory，否则用null + Integer报错
                    inventory = 0;
                    if(isOverSell == 0){
                        Boolean result = redisDao.setnx("awardConfigInventoryLock:" + awardId, msg.getTransactionId(),60L);
                        if(result == false)
                            return ConsumeConcurrentlyStatus.RECONSUME_LATER;
                        String awardInventorySplitKey = "award_inventory_split:" + awardId;
                        List<AwardInventorySplit> list = awardInventorySplitMapper.select(awardId);
                        for(AwardInventorySplit split : list) {
                            inventory += split.getInventory();
                            redisDao.hmSet(awardInventorySplitKey, "splitId:" + split.getSplitId(), split.getInventory());
                        }
                        redisDao.remove("awardConfigInventoryLock:" + awardId);
                    }else{
                        inventory = awardConfigMapper.selectInventory(awardId);
                    }
                    redisDao.set(awardConfigInventoryKey, inventory);
                }

                //从redis、mysql查询userAward的status
                String userAwardStatusKey = "user_award:status:" + userId + ":" + awardId;
                Integer status = (Integer) redisDao.get(userAwardStatusKey);
                if(status == null){
                    status = userAwardMapper.selectStatus(userId, awardId);
                    redisDao.set(userAwardStatusKey, status);
                }

                //从redis、mysql查询user_currency的currency
                String userCurrencyKey = "user_currency:" + userId;
                Integer currency = (Integer) redisDao.get(userCurrencyKey);
                if(currency == null){
                    currency = userCurrencyMapper.selectCurrency(userId);
                    redisDao.set(userCurrencyKey, currency);
                }

                System.out.println("TransactionConsumer.consumeMessage" + "(" + userId + ")" +
                        ":检查是否重复消费...");
                //检查奖品是否已处理，避免重复消费
                if(status != 0){
                    System.out.println("TransactionConsumer.consumeMessage:该消息是重复消息");
                    return ConsumeConcurrentlyStatus.CONSUME_SUCCESS;
                }

                //判断库存
                if(inventory > 0){
                    if(isOverSell == 0) {
                        long start = System.currentTimeMillis();
                        System.out.println("TransactionConsumer.consumeMessage" +"(" + userId + ")" +
                                ":兑换不可超卖商品...");
                        //随机选择库存记录，获取分库存splitInventory
                        String awardInventorySplitKey = "award_inventory_split:" + awardId;
                        Long size = redisDao.getHashSize(awardInventorySplitKey);
                        Set<String> keys = redisDao.getHashKeys(awardInventorySplitKey);
                        ArrayList<String> keyList = new ArrayList<>(keys);
                        System.out.println("TransactionConsumer.consumeMessage" +"(" + userId + ")" +
                                ":随机选择库存记录");
                        Random rand = new Random();
                        int randomIndex = rand.nextInt(size.intValue());
                        String hashKey = keyList.get(randomIndex);
                        Integer splitInventory = (Integer) redisDao.hmGet(awardInventorySplitKey, hashKey);
                        System.out.println("TransactionConsumer.consumeMessage" +"(" + userId + ")" +
                                ":判断分库存是否为0");
                        //如果分库存为0，消费成功，兑换失败
                        if(splitInventory <= 0){
                            System.out.println("TransactionConsumer.consumeMessage" +"(" + userId + ")" +
                                    ":分库存为0，兑换失败");
                            UserAward userAward = new UserAward();
                            userAward.setUserId(userId);
                            userAward.setAwardId(awardId);
                            userAward.setUpdateTime(new Date());
                            userAward.setStatus(-1);//status=-1表示兑换失败
                            userAwardMapper.updateStatus(userAward);
                            System.out.println("TransactionConsumer.consumeMessage" +"(" + userId + ")" +
                                    ":兑换失败");
                            return ConsumeConcurrentlyStatus.CONSUME_SUCCESS;
                        }

                        //加锁
                        String lockKey = "inventoryLock:"  + awardId + ":" + hashKey;
                        String lockValue = msg.getTransactionId();
                        System.out.println("TransactionConsumer.consumeMessage" +"(" + userId + ")" +
                                ":加锁中...");
                        Boolean result = redisDao.setnx(lockKey, lockValue,10L);
                        if(result == false){
                            System.out.println("TransactionConsumer.consumeMessage" +"(" + userId + ")" +
                                    ":加锁失败，稍后重试");
                            return ConsumeConcurrentlyStatus.RECONSUME_LATER;
                        }else {
                            System.out.println("TransactionConsumer.consumeMessage" +"(" + userId + ")" +
                                    ":加锁成功");
                        }

                        //扣减分库存
                        AwardInventorySplit awardInventorySplit = new AwardInventorySplit();
                        awardInventorySplit.setSplitId(Long.valueOf(hashKey.substring(hashKey.indexOf(":") + 1)));
                        awardInventorySplit.setAwardId(awardId);

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
                        System.out.println("TransactionConsumer.consumeMessage" +"(" + userId + ")" +
                                ":执行事务update1");
                        try{
                            consumerService.update1(awardInventorySplit, userCurrency, userAward, lockKey, lockValue);
                        }catch (Exception e){
                            System.out.println(e);
                            return ConsumeConcurrentlyStatus.RECONSUME_LATER;
                        }
                        System.out.println("TransactionConsumer.consumeMessage" +"(" + userId + ")" +
                                ":释放锁");
                        redisDao.remove(lockKey);
                        long finish = System.currentTimeMillis();
                        System.out.println("执行时间：" + (finish - start) + "毫秒"+"(" + userId + ")");
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