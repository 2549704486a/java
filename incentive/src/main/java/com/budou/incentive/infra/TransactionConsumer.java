package com.budou.incentive.infra;

import com.budou.incentive.config.OldChainRetryProperties;
import com.budou.incentive.dao.mapper.AwardConfigMapper;
import com.budou.incentive.dao.mapper.UserAwardMapper;
import com.budou.incentive.dao.model.UserAward;
import com.budou.incentive.dao.redis.RedisDao;
import com.budou.incentive.service.ConsumerService;
import com.budou.incentive.utils.SeckillObservability;
import com.budou.incentive.utils.SeckillRedisKeys;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.github.benmanes.caffeine.cache.Cache;
import org.apache.rocketmq.client.consumer.listener.ConsumeConcurrentlyContext;
import org.apache.rocketmq.client.consumer.listener.ConsumeConcurrentlyStatus;
import org.apache.rocketmq.client.consumer.listener.MessageListenerConcurrently;
import org.apache.rocketmq.common.message.MessageExt;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.stereotype.Service;

import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.Date;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;

@Service
public class TransactionConsumer implements MessageListenerConcurrently {
    private static final long FAILED_STATUS_TTL_SECONDS = 300L;
    private static final String OLD_CHAIN_RETRY_COUNT_KEY = "oldChainRetryCount";
    private static final String OLD_CHAIN_RETRY_REASON_KEY = "oldChainRetryReason";

    @Autowired
    private ConsumerService consumerService;
    @Autowired
    private UserAwardMapper userAwardMapper;
    @Autowired
    private AwardConfigMapper awardConfigMapper;
    @Autowired
    private RedisDao redisDao;
    @Autowired
    private SeckillObservability seckillObservability;
    @Autowired
    private TransactionProducer transactionProducer;
    @Autowired
    private ObjectMapper objectMapper;
    @Autowired
    private OldChainRetryProperties oldChainRetryProperties;

    @Autowired
    @Qualifier("awardPriceCache")
    private Cache<Long, Integer> awardPriceCache;

    @Autowired
    @Qualifier("awardIsOverSellCache")
    private Cache<Long, Integer> awardIsOverSellCache;

    @Override
    public ConsumeConcurrentlyStatus consumeMessage(List<MessageExt> msgs, ConsumeConcurrentlyContext context) {
        // 消费者配置固定为单条批次：解析消息后进入旧链路，异常时优先投递自定义延时消息。
        for (MessageExt msg : msgs) {
            Long userId = null;
            Long awardId = null;
            Long id = null;
            long messageStartMillis = msg.getBornTimestamp();
            Map<String, Object> data = null;
            try {
                data = objectMapper.readValue(
                        new String(msg.getBody(), StandardCharsets.UTF_8), Map.class);
                userId = Long.valueOf(String.valueOf(data.get("userId")));
                awardId = Long.valueOf(String.valueOf(data.get("awardId")));
                id = Long.valueOf(String.valueOf(data.get("id")));
                messageStartMillis = resolveMessageStartMillis(data, msg);
                return consumeOldChainMessage(data, id, userId, awardId, messageStartMillis);
            } catch (Exception e) {
                if (data != null && id != null && userId != null && awardId != null
                        && scheduleOldChainDelayedRetry(data, id, userId, awardId,
                        resolveOldChainRetryCount(data), "consume-exception:" + e.getClass().getSimpleName())) {
                    return ConsumeConcurrentlyStatus.CONSUME_SUCCESS;
                }
                seckillObservability.recordReconsumeLater(id, userId, awardId,
                        "consume-exception:" + e.getClass().getSimpleName());
                return ConsumeConcurrentlyStatus.RECONSUME_LATER;
            }
        }

        return ConsumeConcurrentlyStatus.CONSUME_SUCCESS;
    }

    private ConsumeConcurrentlyStatus consumeOldChainMessage(Map<String, Object> data, Long id, Long userId,
                                                              Long awardId, long messageStartMillis) {
        // 消息可能因延时重试或 Broker 重投而重复到达，先用最终状态短路已完成订单。
        if (isOrderAlreadyFinished(userId, awardId)) {
            return ConsumeConcurrentlyStatus.CONSUME_SUCCESS;
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
            recordOldChainFailure(id, userId, awardId, messageStartMillis, "price-not-found");
            markOldChainFailed(id, userId, awardId);
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

        if (isOverSell != 0) {
            // 允许超卖的奖品不走分片库存扣减，只执行扣积分和完成订单。
            return consumeOverSellMessage(id, userId, awardId, price, messageStartMillis);
        }

        // 第一层循环：普通奖品先在当前消费线程内重试若干轮。
        // 每一轮都会重新读取 Redis 分片集合，因此上一轮的锁释放、库存同步等变化可以被下一轮看到。
        int retryCount = resolveOldChainRetryCount(data);
        int lockAttemptRounds = Math.max(oldChainRetryProperties.getLockAttemptRounds(), 1);
        String lastRetryReason = "all-splits-locked";

        for (int round = 0; round < lockAttemptRounds; round++) {
            // 一轮会从一个哈希起点出发，最多把当前全部候选分片探测一遍。
            OldChainRoundResult roundResult = tryConsumeOldChainRound(
                    id, userId, awardId, price, messageStartMillis, retryCount, round
            );
            if (roundResult.disposition() == OldChainRoundDisposition.SUCCESS) {
                // 已完成数据库事务或确认是重复消费，当前 RocketMQ 消息可以被确认。
                return ConsumeConcurrentlyStatus.CONSUME_SUCCESS;
            }
            if (roundResult.disposition() == OldChainRoundDisposition.TERMINAL_FAIL) {
                // 库存确定耗尽、积分不足等不可通过重试恢复的问题，直接把订单置为失败。
                markOldChainFailed(id, userId, awardId);
                return ConsumeConcurrentlyStatus.CONSUME_SUCCESS;
            }
            // 可重试结果通常来自分片锁冲突或临时数据库异常，记录原因供延时重试埋点使用。
            lastRetryReason = roundResult.reason();
            if (round < lockAttemptRounds - 1) {
                // 短暂退避后再开始新一轮，避免立即重复争抢同一批分片锁。
                backoffBeforeNextRound(round);
            }
        }

        // 线程内所有轮次结束后再次检查 Hash。Hash 已空表示没有候选库存，不再投递延时消息。
        String awardInventorySplitKey = "award_inventory_split:" + awardId;
        Long leftSize = redisDao.getHashSize(awardInventorySplitKey);
        if (leftSize == null || leftSize == 0) {
            recordOldChainFailure(id, userId, awardId, messageStartMillis, "split-inventory-empty");
            markOldChainFailed(id, userId, awardId);
            return ConsumeConcurrentlyStatus.CONSUME_SUCCESS;
        }

        // 线程内重试仍未成功时发送延时消息，并确认原消息，给锁冲突留出消退时间。
        if (scheduleOldChainDelayedRetry(data, id, userId, awardId, retryCount, lastRetryReason)) {
            return ConsumeConcurrentlyStatus.CONSUME_SUCCESS;
        }

        seckillObservability.recordReconsumeLater(id, userId, awardId, "delay-send-failed:" + lastRetryReason);
        return ConsumeConcurrentlyStatus.RECONSUME_LATER;
    }

    private OldChainRoundResult tryConsumeOldChainRound(Long id, Long userId, Long awardId, Integer price,
                                                        long messageStartMillis,
                                                        int retryCount, int round) {
        // Redis 使用一个 Hash 保存某个奖品的分片：
        // key = award_inventory_split:<awardId>，field = split:<splitId>，value = 当前分片库存。
        String awardInventorySplitKey = "award_inventory_split:" + awardId;
        // HLEN 只表示当前还有多少个候选分片字段，不代表这些分片的库存总和。
        Long size = redisDao.getHashSize(awardInventorySplitKey);
        if (size == null || size == 0) {
            recordOldChainFailure(id, userId, awardId, messageStartMillis, "split-size-empty");
            return OldChainRoundResult.terminalFail("split-size-empty");
        }

        // 第二层：获取本轮候选分片字段的快照。后续真正使用某个分片前还会再次读取它的库存。
        Set<String> keys = redisDao.getHashKeys(awardInventorySplitKey);
        if (keys == null || keys.isEmpty()) {
            recordOldChainFailure(id, userId, awardId, messageStartMillis, "split-keys-empty");
            return OldChainRoundResult.terminalFail("split-keys-empty");
        }

        // Redis 返回的 Set 没有稳定顺序，先按 splitId 排序，保证相同输入得到相同的环形分片序列。
        ArrayList<String> keyList = new ArrayList<>(keys);
        keyList.sort(Comparator.comparingLong(this::extractSplitId));

        // 用订单 id 计算首选分片，使不同订单尽量从不同位置开始，降低所有消费者争抢首分片的概率。
        // retryCount 是延时消息重试次数，round 是当前线程内轮次；加入它们可让重试时更换探测起点。
        int preferredIndex = preferredSplitIndex(id + retryCount * 31L + round, keyList.size());
        boolean encounteredLockConflict = false;

        // 第三层：从首选下标开始线性探测。offset 递增，取模后会从数组末尾绕回开头，
        // 因此一次循环最多检查 keyList 中的每个分片一次，不会漏掉首选分片之前的元素。
        for (int offset = 0; offset < keyList.size(); offset++) {
            String hashKey = keyList.get((preferredIndex + offset) % keyList.size());
            String lockKey = "inventoryLock:award:" + awardId + ":split:" + hashKey;
            // 每次加锁生成独立所有者标识，释放时只删除仍由自己持有的锁。
            String lockValue = UUID.randomUUID().toString();

            // SET NX EX：只有锁不存在时才能写入，并设置过期时间防止消费者异常退出后永久占锁。
            boolean locked = Boolean.TRUE.equals(
                    redisDao.setnx(lockKey, lockValue, oldChainRetryProperties.getSplitLockExpireSeconds())
            );
            if (!locked) {
                // 当前分片正被其他消费者处理。本线程不阻塞等待，而是立即探测下一个分片。
                encounteredLockConflict = true;
                seckillObservability.recordLockFail(id, userId, awardId, hashKey);
                continue;
            }

            try {
                // 拿到锁后重新读取该字段，而不是完全相信上面的 keys 快照，因为库存可能已经发生变化。
                // Redis 分片库存只用于快速筛选，真正防止库存扣成负数的是数据库的条件更新。
                Integer splitInventory = (Integer) redisDao.hmGet(awardInventorySplitKey, hashKey);
                if (splitInventory == null || splitInventory <= 0) {
                    // 该分片已经没有库存，将它从 Redis 候选集合移除，然后继续探测下一个分片。
                    // 此处只清理缓存字段，不修改数据库库存。
                    redisDao.hmDel(awardInventorySplitKey, hashKey);
                    continue;
                }

                try {
                    // Redis 判断通过后进入最终数据库事务：
                    // 1. 插入幂等键；2. 条件扣减指定分片；3. 条件扣积分；4. 将订单状态改为成功。
                    consumerService.update1(id, userId, awardId, price, extractSplitId(hashKey));
                    // 数据库事务成功后再更新查询缓存，用户随后查询 /result 时可以直接得到成功状态。
                    redisDao.set(SeckillRedisKeys.buildStatusKey(userId, awardId), 1);
                    recordOldChainSuccess(id, userId, awardId, messageStartMillis, "consume-success");
                    return OldChainRoundResult.success();
                } catch (DuplicateKeyException e) {
                    // 幂等键已存在，说明该用户奖品已经处理过，重复消息可以直接确认。
                    redisDao.set(SeckillRedisKeys.buildStatusKey(userId, awardId), 1);
                    recordOldChainSuccess(id, userId, awardId, messageStartMillis, "duplicate-consume");
                    return OldChainRoundResult.success();
                } catch (IllegalStateException e) {
                    String businessCode = normalizeBusinessCode(e.getMessage());
                    if ("split-inventory-empty".equals(businessCode)) {
                        // Redis 显示有库存但数据库条件扣减返回 0，说明缓存快照已经过期。
                        // 删除该候选分片并继续探测其他分片，而不是立刻判定整个奖品售罄。
                        redisDao.hmDel(awardInventorySplitKey, hashKey);
                        continue;
                    }
                    if ("currency-not-enough".equals(businessCode)) {
                        // 积分不足对当前用户是确定性结果，更换分片或稍后重试都没有意义。
                        recordOldChainFailure(id, userId, awardId, messageStartMillis, businessCode);
                        return OldChainRoundResult.terminalFail(businessCode);
                    }
                    // 其他业务异常暂时按可重试处理，交给外层线程内重试或延时消息处理。
                    return OldChainRoundResult.retryable("update1-" + businessCode);
                } catch (Exception e) {
                    // 未识别的数据库或基础设施异常不立即置失败，保留再次消费的机会。
                    return OldChainRoundResult.retryable("update1-" + e.getClass().getSimpleName());
                }
            } finally {
                // 无论成功、失败还是 continue，都尝试释放当前分片锁。
                releaseLockIfOwned(lockKey, lockValue);
            }
        }

        // 本轮所有候选分片都检查完仍未成功：
        // 出现过锁冲突时说明库存可能只是暂时不可访问；否则说明当前快照中没有可扣减分片。
        return OldChainRoundResult.retryable(encounteredLockConflict ? "all-splits-locked" : "no-split-available");
    }

    private ConsumeConcurrentlyStatus consumeOverSellMessage(Long id, Long userId, Long awardId, Integer price,
                                                             long messageStartMillis) {
        try {
            consumerService.update2(id, userId, awardId, price);

            String awardConfigInventoryKey = "award_config:inventory:" + awardId;
            redisDao.decrement(awardConfigInventoryKey);
            recordOldChainSuccess(id, userId, awardId, messageStartMillis,
                    "consume-success-over-sell");
        } catch (Exception e) {
            markOldChainFailed(id, userId, awardId);
            recordOldChainFailure(id, userId, awardId, messageStartMillis, "update2-exception");
        }
        return ConsumeConcurrentlyStatus.CONSUME_SUCCESS;
    }

    private boolean isOrderAlreadyFinished(Long userId, Long awardId) {
        // Redis 只承担快速判断，缓存缺失时仍回源数据库确认最终状态。
        String statusKey = SeckillRedisKeys.buildStatusKey(userId, awardId);
        Integer redisStatus = (Integer) redisDao.get(statusKey);
        if (redisStatus != null && (redisStatus == 1 || redisStatus == -1)) {
            return true;
        }

        Integer dbStatus = userAwardMapper.selectStatus(userId, awardId);
        if (dbStatus == null || dbStatus == 0) {
            return false;
        }
        if (dbStatus == 1) {
            redisDao.set(statusKey, 1);
            return true;
        }
        redisDao.set(statusKey, -1, FAILED_STATUS_TTL_SECONDS);
        return true;
    }

    private boolean scheduleOldChainDelayedRetry(Map<String, Object> data, Long id, Long userId, Long awardId,
                                                 int currentRetryCount, String reason) {
        // 自定义重试次数写回消息体，使每次重投都能选择对应的 RocketMQ 延迟级别。
        if (!oldChainRetryProperties.isDelayedRetryEnabled()) {
            return false;
        }
        if (currentRetryCount >= oldChainRetryProperties.getDelayedRetryMaxTimes()) {
            return false;
        }

        int nextRetryCount = currentRetryCount + 1;
        int delayLevel = oldChainRetryProperties.resolveDelayLevel(nextRetryCount);
        if (delayLevel <= 0) {
            return false;
        }

        try {
            Map<String, Object> retryData = new HashMap<>(data);
            retryData.put(OLD_CHAIN_RETRY_COUNT_KEY, nextRetryCount);
            retryData.put(OLD_CHAIN_RETRY_REASON_KEY, reason);
            String payload = objectMapper.writeValueAsString(retryData);
            boolean sent = transactionProducer.sendDelayMessage(String.valueOf(id), payload, delayLevel);
            if (sent) {
                seckillObservability.recordDelayedRetryScheduled(id, userId, awardId, nextRetryCount, delayLevel, reason);
            }
            return sent;
        } catch (Exception e) {
            return false;
        }
    }

    private int resolveOldChainRetryCount(Map<String, Object> data) {
        Object retryCount = data.get(OLD_CHAIN_RETRY_COUNT_KEY);
        if (retryCount == null) {
            return 0;
        }
        try {
            return Math.max(Integer.parseInt(String.valueOf(retryCount)), 0);
        } catch (NumberFormatException ex) {
            return 0;
        }
    }

    private void backoffBeforeNextRound(int round) {
        long backoffMillis = oldChainRetryProperties.resolveLockBackoffMillis(round);
        if (backoffMillis <= 0) {
            return;
        }
        try {
            Thread.sleep(backoffMillis);
        } catch (InterruptedException ex) {
            Thread.currentThread().interrupt();
        }
    }

    private void releaseLockIfOwned(String lockKey, String lockValue) {
        Object currentValue = redisDao.get(lockKey);
        if (lockValue.equals(String.valueOf(currentValue))) {
            redisDao.remove(lockKey);
        }
    }

    private void recordOldChainSuccess(Long id, Long userId, Long awardId,
                                       long messageStartMillis, String outcome) {
        seckillObservability.recordMessageCompletion(id, userId, awardId, true,
                elapsedSince(messageStartMillis), outcome);
    }

    private void recordOldChainFailure(Long id, Long userId, Long awardId,
                                       long messageStartMillis, String outcome) {
        seckillObservability.recordMessageCompletion(id, userId, awardId, false,
                elapsedSince(messageStartMillis), outcome);
    }

    private String normalizeBusinessCode(String code) {
        if (code == null || code.isBlank()) {
            return "unknown";
        }
        return code.trim();
    }

    private void markOldChainFailed(Long id, Long userId, Long awardId) {
        // 终态失败同时写 MySQL 和短期 Redis 状态，让结果查询不再停留在 status=0。
        UserAward userAward = new UserAward();
        userAward.setId(id);
        userAward.setUpdateTime(new Date());
        userAward.setStatus(-1);
        userAwardMapper.updateStatus(userAward);
        redisDao.set(SeckillRedisKeys.buildStatusKey(userId, awardId), -1, FAILED_STATUS_TTL_SECONDS);
    }

    private long resolveMessageStartMillis(Map<String, Object> data, MessageExt msg) {
        Object messageTimeMillis = data.get("messageTimeMillis");
        if (messageTimeMillis == null) {
            return msg.getBornTimestamp();
        }
        try {
            return Long.parseLong(String.valueOf(messageTimeMillis));
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
        // floorMod 保证哈希值即使为负数，也能得到 [0, splitCount) 范围内的合法下标。
        return Math.floorMod(Long.hashCode(orderId), splitCount);
    }

    private long extractSplitId(String hashKey) {
        // 把 Redis Hash 字段 split:<splitId> 解析成数据库 award_inventory_split.splitId。
        int separator = hashKey.indexOf(':');
        if (separator < 0 || separator == hashKey.length() - 1) {
            throw new IllegalArgumentException("Unexpected split key: " + hashKey);
        }
        return Long.parseLong(hashKey.substring(separator + 1));
    }

    private enum OldChainRoundDisposition {
        SUCCESS,
        TERMINAL_FAIL,
        RETRYABLE
    }

    private record OldChainRoundResult(OldChainRoundDisposition disposition, String reason) {
        private static OldChainRoundResult success() {
            return new OldChainRoundResult(OldChainRoundDisposition.SUCCESS, "success");
        }

        private static OldChainRoundResult terminalFail(String reason) {
            return new OldChainRoundResult(OldChainRoundDisposition.TERMINAL_FAIL, reason);
        }

        private static OldChainRoundResult retryable(String reason) {
            return new OldChainRoundResult(OldChainRoundDisposition.RETRYABLE, reason);
        }
    }
}
