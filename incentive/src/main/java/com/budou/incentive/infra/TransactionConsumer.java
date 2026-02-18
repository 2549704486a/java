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

    @Override
    //ConsumeConcurrentlyContext：1获取当前消费的队列信息2设置消息重试延迟3帮助处理并发消费时的重试策略与消息状态管理。
    public ConsumeConcurrentlyStatus consumeMessage(List<MessageExt> msgs, ConsumeConcurrentlyContext context) {
        for (MessageExt msg : msgs) {
            // 解析数据
            System.out.println("我来啦");
            ObjectMapper objectMapper = new ObjectMapper();
            Map data;
            try {
                data = objectMapper.readValue(new String(msg.getBody(), StandardCharsets.UTF_8), Map.class);
            } catch (Exception e) {
                throw new RuntimeException(e);
            }
            Long userId = Long.valueOf(String.valueOf(data.get("userId")));
            Long awardId = Long.valueOf(String.valueOf(data.get("awardId")));
            Long id = Long.valueOf(String.valueOf(data.get("id")));


            //从redis、mysql查询商品的price、isOverSell
            String awardConfigPriceKey = "award_config:price:" + awardId;
            Integer price = (Integer) redisDao.get(awardConfigPriceKey);
            String awardConfigIsOverSellKey = "award_config:isOverSell:" + awardId;
            Integer isOverSell = (Integer) redisDao.get(awardConfigIsOverSellKey);


            if(isOverSell == 0) {
                // 检查是否有库存
                String awardInventorySplitKey = "award_inventory_split:" + awardId;
                Long size = redisDao.getHashSize(awardInventorySplitKey);
                if(size == 0){
                    exchangeFail(id);
                    System.out.println("fail1");
                    return ConsumeConcurrentlyStatus.CONSUME_SUCCESS;
                }

                // 随机选择分片，加锁
                Set<String> keys = redisDao.getHashKeys(awardInventorySplitKey);
                ArrayList<String> keyList = new ArrayList<>(keys);
                Random rand = new Random();
                int randomIndex = rand.nextInt(size.intValue());
                String hashKey = keyList.get(randomIndex);
                String lockKey = "inventoryLock:"  + awardId + ":" + hashKey;
                String lockValue = UUID.randomUUID().toString();
                Boolean result = redisDao.setnx(lockKey, lockValue,10L);
                if(result == false){
                    return ConsumeConcurrentlyStatus.RECONSUME_LATER;
                }


                // 检查该分片是否有余量
                Integer splitInventory = (Integer) redisDao.hmGet(awardInventorySplitKey, hashKey);
                if(splitInventory <= 0){
                    redisDao.hmDel(awardInventorySplitKey,hashKey);
                    return ConsumeConcurrentlyStatus.RECONSUME_LATER;
                }


                // 更新数据库
                try{
                    consumerService.update1(id, userId, awardId, price,
                            Long.valueOf(hashKey.substring(hashKey.indexOf(":") + 1 )));
                }catch (Exception e){
                    redisDao.remove(lockKey);
                    System.out.println("fail2");
                    exchangeFail(id);
                    return ConsumeConcurrentlyStatus.CONSUME_SUCCESS;
                }
                redisDao.remove(lockKey);
            } else {
                //执行事务
                try{
                    consumerService.update2(id, userId, awardId, price);

                    //扣减库存,update2成功了，就扣减库存，无论decrement是否成功，都算兑换成功
                    redisDao.decrement("award_config:inventory:" + awardId);
                } catch (Exception e){
                    System.out.println(e);
                    userAwardMapper.updateStatusFail(id);
                }
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