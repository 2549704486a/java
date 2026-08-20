package com.budou.incentive.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

import java.util.ArrayList;
import java.util.List;

@ConfigurationProperties(prefix = "seckill.old-chain")
public class OldChainRetryProperties {
    private int lockAttemptRounds = 2;
    private List<Long> lockRetryBackoffMillis = new ArrayList<>(List.of(5L, 15L));
    private long splitLockExpireSeconds = 10L;
    private boolean delayedRetryEnabled = true;
    private int delayedRetryMaxTimes = 6;
    private List<Integer> delayedRetryDelayLevels = new ArrayList<>(List.of(1, 1, 2, 2, 3, 4));

    public int getLockAttemptRounds() {
        return lockAttemptRounds;
    }

    public void setLockAttemptRounds(int lockAttemptRounds) {
        this.lockAttemptRounds = lockAttemptRounds;
    }

    public List<Long> getLockRetryBackoffMillis() {
        return lockRetryBackoffMillis;
    }

    public void setLockRetryBackoffMillis(List<Long> lockRetryBackoffMillis) {
        this.lockRetryBackoffMillis = lockRetryBackoffMillis;
    }

    public long getSplitLockExpireSeconds() {
        return splitLockExpireSeconds;
    }

    public void setSplitLockExpireSeconds(long splitLockExpireSeconds) {
        this.splitLockExpireSeconds = splitLockExpireSeconds;
    }

    public boolean isDelayedRetryEnabled() {
        return delayedRetryEnabled;
    }

    public void setDelayedRetryEnabled(boolean delayedRetryEnabled) {
        this.delayedRetryEnabled = delayedRetryEnabled;
    }

    public int getDelayedRetryMaxTimes() {
        return delayedRetryMaxTimes;
    }

    public void setDelayedRetryMaxTimes(int delayedRetryMaxTimes) {
        this.delayedRetryMaxTimes = delayedRetryMaxTimes;
    }

    public List<Integer> getDelayedRetryDelayLevels() {
        return delayedRetryDelayLevels;
    }

    public void setDelayedRetryDelayLevels(List<Integer> delayedRetryDelayLevels) {
        this.delayedRetryDelayLevels = delayedRetryDelayLevels;
    }

    public long resolveLockBackoffMillis(int round) {
        if (lockRetryBackoffMillis == null || lockRetryBackoffMillis.isEmpty()) {
            return 0L;
        }
        int index = Math.max(0, Math.min(round, lockRetryBackoffMillis.size() - 1));
        return Math.max(lockRetryBackoffMillis.get(index), 0L);
    }

    public int resolveDelayLevel(int retryAttempt) {
        if (delayedRetryDelayLevels == null || delayedRetryDelayLevels.isEmpty()) {
            return 0;
        }
        int index = Math.max(0, Math.min(retryAttempt - 1, delayedRetryDelayLevels.size() - 1));
        return Math.max(delayedRetryDelayLevels.get(index), 0);
    }
}
