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
            return consumeOverSellMessage(id, userId, awardId, price, messageStartMillis);
        }

        int retryCount = resolveOldChainRetryCount(data);
        int lockAttemptRounds = Math.max(oldChainRetryProperties.getLockAttemptRounds(), 1);
        String lastRetryReason = "all-splits-locked";

        for (int round = 0; round < lockAttemptRounds; round++) {
            OldChainRoundResult roundResult = tryConsumeOldChainRound(
                    id, userId, awardId, price, messageStartMillis, retryCount, round
            );
            if (roundResult.disposition() == OldChainRoundDisposition.SUCCESS) {
                return ConsumeConcurrentlyStatus.CONSUME_SUCCESS;
            }
            if (roundResult.disposition() == OldChainRoundDisposition.TERMINAL_FAIL) {
                markOldChainFailed(id, userId, awardId);
                return ConsumeConcurrentlyStatus.CONSUME_SUCCESS;
            }
            lastRetryReason = roundResult.reason();
            if (round < lockAttemptRounds - 1) {
                backoffBeforeNextRound(round);
            }
        }

        String awardInventorySplitKey = "award_inventory_split:" + awardId;
        Long leftSize = redisDao.getHashSize(awardInventorySplitKey);
        if (leftSize == null || leftSize == 0) {
            recordOldChainFailure(id, userId, awardId, messageStartMillis, "split-inventory-empty");
            markOldChainFailed(id, userId, awardId);
            return ConsumeConcurrentlyStatus.CONSUME_SUCCESS;
        }

        if (scheduleOldChainDelayedRetry(data, id, userId, awardId, retryCount, lastRetryReason)) {
            return ConsumeConcurrentlyStatus.CONSUME_SUCCESS;
        }

        seckillObservability.recordReconsumeLater(id, userId, awardId, "delay-send-failed:" + lastRetryReason);
        return ConsumeConcurrentlyStatus.RECONSUME_LATER;
    }

    private OldChainRoundResult tryConsumeOldChainRound(Long id, Long userId, Long awardId, Integer price,
                                                        long messageStartMillis,
                                                        int retryCount, int round) {
        String awardInventorySplitKey = "award_inventory_split:" + awardId;
        Long size = redisDao.getHashSize(awardInventorySplitKey);
        if (size == null || size == 0) {
            recordOldChainFailure(id, userId, awardId, messageStartMillis, "split-size-empty");
            return OldChainRoundResult.terminalFail("split-size-empty");
        }

        Set<String> keys = redisDao.getHashKeys(awardInventorySplitKey);
        if (keys == null || keys.isEmpty()) {
            recordOldChainFailure(id, userId, awardId, messageStartMillis, "split-keys-empty");
            return OldChainRoundResult.terminalFail("split-keys-empty");
        }

        ArrayList<String> keyList = new ArrayList<>(keys);
        keyList.sort(Comparator.comparingLong(this::extractSplitId));

        int preferredIndex = preferredSplitIndex(id + retryCount * 31L + round, keyList.size());
        boolean encounteredLockConflict = false;

        for (int offset = 0; offset < keyList.size(); offset++) {
            String hashKey = keyList.get((preferredIndex + offset) % keyList.size());
            String lockKey = "inventoryLock:award:" + awardId + ":split:" + hashKey;
            String lockValue = UUID.randomUUID().toString();

            boolean locked = Boolean.TRUE.equals(
                    redisDao.setnx(lockKey, lockValue, oldChainRetryProperties.getSplitLockExpireSeconds())
            );
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
                    consumerService.update1(id, userId, awardId, price, extractSplitId(hashKey));
                    redisDao.set(SeckillRedisKeys.buildStatusKey(userId, awardId), 1);
                    recordOldChainSuccess(id, userId, awardId, messageStartMillis, "consume-success");
                    return OldChainRoundResult.success();
                } catch (DuplicateKeyException e) {
                    redisDao.set(SeckillRedisKeys.buildStatusKey(userId, awardId), 1);
                    recordOldChainSuccess(id, userId, awardId, messageStartMillis, "duplicate-consume");
                    return OldChainRoundResult.success();
                } catch (IllegalStateException e) {
                    String businessCode = normalizeBusinessCode(e.getMessage());
                    if ("split-inventory-empty".equals(businessCode)) {
                        redisDao.hmDel(awardInventorySplitKey, hashKey);
                        continue;
                    }
                    if ("currency-not-enough".equals(businessCode)) {
                        recordOldChainFailure(id, userId, awardId, messageStartMillis, businessCode);
                        return OldChainRoundResult.terminalFail(businessCode);
                    }
                    return OldChainRoundResult.retryable("update1-" + businessCode);
                } catch (Exception e) {
                    return OldChainRoundResult.retryable("update1-" + e.getClass().getSimpleName());
                }
            } finally {
                releaseLockIfOwned(lockKey, lockValue);
            }
        }

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
        return Math.floorMod(Long.hashCode(orderId), splitCount);
    }

    private long extractSplitId(String hashKey) {
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
