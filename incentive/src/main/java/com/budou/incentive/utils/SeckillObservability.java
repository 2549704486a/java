package com.budou.incentive.utils;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import java.util.concurrent.atomic.AtomicLong;
import java.util.concurrent.atomic.LongAdder;

@Component
public class SeckillObservability {

    private static final Logger log = LoggerFactory.getLogger(SeckillObservability.class);

    private final LongAdder requestAcceptedCount = new LongAdder();
    private final LongAdder lockFailCount = new LongAdder();
    private final LongAdder reconsumeLaterCount = new LongAdder();
    private final LongAdder completionSuccessCount = new LongAdder();
    private final LongAdder completionFailCount = new LongAdder();
    private final LongAdder deadLetterCount = new LongAdder();
    private final LongAdder completionLatencyCount = new LongAdder();
    private final LongAdder completionLatencyTotalMs = new LongAdder();
    private final LongAdder completionOver1sCount = new LongAdder();
    private final LongAdder completionOver5sCount = new LongAdder();
    private final LongAdder completionOver30sCount = new LongAdder();
    private final AtomicLong maxCompletionLatencyMs = new AtomicLong();

    public void recordRequestAccepted(Long orderId, Long userId, Long awardId) {
        requestAcceptedCount.increment();
        log.debug("SECKILL_METRICS request accepted orderId={} userId={} awardId={}", orderId, userId, awardId);
    }

    public void recordLockFail(Long orderId, Long userId, Long awardId, String splitKey) {
        lockFailCount.increment();
        log.debug("SECKILL_METRICS lock failed orderId={} userId={} awardId={} splitKey={}",
                orderId, userId, awardId, splitKey);
    }

    public void recordReconsumeLater(Long orderId, Long userId, Long awardId, String reason) {
        reconsumeLaterCount.increment();
        log.debug("SECKILL_METRICS reconsume later orderId={} userId={} awardId={} reason={}",
                orderId, userId, awardId, reason);
    }

    public void recordCompletion(Long orderId, Long userId, Long awardId, boolean success,
                                 long latencyMs, String outcome) {
        if (success) {
            completionSuccessCount.increment();
        } else {
            completionFailCount.increment();
        }
        recordLatency(latencyMs);
        if (latencyMs >= 5000) {
            log.warn("SECKILL_METRICS slow completion orderId={} userId={} awardId={} success={} latencyMs={} outcome={}",
                    orderId, userId, awardId, success, latencyMs, outcome);
        }
    }

    public void recordDeadLetter(Long orderId, Long userId, Long awardId, long latencyMs) {
        deadLetterCount.increment();
        recordCompletion(orderId, userId, awardId, false, latencyMs, "dead-letter");
    }

    private void recordLatency(long latencyMs) {
        long nonNegativeLatency = Math.max(latencyMs, 0L);
        completionLatencyCount.increment();
        completionLatencyTotalMs.add(nonNegativeLatency);
        maxCompletionLatencyMs.accumulateAndGet(nonNegativeLatency, Math::max);
        if (nonNegativeLatency >= 1000) {
            completionOver1sCount.increment();
        }
        if (nonNegativeLatency >= 5000) {
            completionOver5sCount.increment();
        }
        if (nonNegativeLatency >= 30000) {
            completionOver30sCount.increment();
        }
    }

    @Scheduled(fixedRate = 30000)
    public void logSnapshot() {
        long latencyCount = completionLatencyCount.sum();
        double avgLatencyMs = latencyCount == 0 ? 0.0 : (double) completionLatencyTotalMs.sum() / latencyCount;
        log.info(
                "SECKILL_METRICS snapshot requestAccepted={} success={} fail={} deadLetter={} lockFail={} reconsumeLater={} completionAvgMs={} completionMaxMs={} completionOver1s={} completionOver5s={} completionOver30s={}",
                requestAcceptedCount.sum(),
                completionSuccessCount.sum(),
                completionFailCount.sum(),
                deadLetterCount.sum(),
                lockFailCount.sum(),
                reconsumeLaterCount.sum(),
                String.format("%.2f", avgLatencyMs),
                maxCompletionLatencyMs.get(),
                completionOver1sCount.sum(),
                completionOver5sCount.sum(),
                completionOver30sCount.sum()
        );
    }
}
