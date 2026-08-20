package com.budou.incentive.utils;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.concurrent.ConcurrentLinkedQueue;
import java.util.concurrent.atomic.AtomicLong;
import java.util.concurrent.atomic.LongAdder;

@Component
public class SeckillObservability {

    private static final Logger log = LoggerFactory.getLogger(SeckillObservability.class);

    private final LongAdder requestAcceptedCount = new LongAdder();
    private final LongAdder lockFailCount = new LongAdder();
    private final LongAdder reconsumeLaterCount = new LongAdder();
    private final LongAdder delayedRetryScheduledCount = new LongAdder();
    private final LongAdder completionSuccessCount = new LongAdder();
    private final LongAdder completionFailCount = new LongAdder();
    private final LongAdder deadLetterCount = new LongAdder();
    private final LongAdder completionLatencyTotalMs = new LongAdder();
    private final AtomicLong maxCompletionLatencyMs = new AtomicLong();
    private final ConcurrentLinkedQueue<Long> completionLatencySamples = new ConcurrentLinkedQueue<>();

    public void recordRequestAccepted(Long orderId, Long userId, Long awardId) {
        requestAcceptedCount.increment();
    }

    public void recordLockFail(Long orderId, Long userId, Long awardId, String splitKey) {
        lockFailCount.increment();
    }

    public void recordReconsumeLater(Long orderId, Long userId, Long awardId, String reason) {
        reconsumeLaterCount.increment();
    }

    public void recordDelayedRetryScheduled(Long orderId, Long userId, Long awardId,
                                            int retryCount, int delayLevel, String reason) {
        delayedRetryScheduledCount.increment();
    }

    public void recordMessageCompletion(Long orderId, Long userId, Long awardId, boolean success,
                                        long latencyMs, String outcome) {
        long nonNegativeLatency = Math.max(latencyMs, 0L);
        if (success) {
            completionSuccessCount.increment();
        } else {
            completionFailCount.increment();
        }
        completionLatencyTotalMs.add(nonNegativeLatency);
        maxCompletionLatencyMs.accumulateAndGet(nonNegativeLatency, Math::max);
        completionLatencySamples.add(nonNegativeLatency);
    }

    public void recordDeadLetter(Long orderId, Long userId, Long awardId, long latencyMs) {
        deadLetterCount.increment();
        recordMessageCompletion(orderId, userId, awardId, false, latencyMs, "dead-letter");
    }

    @Scheduled(fixedRate = 30000)
    public void logSnapshot() {
        long accepted = requestAcceptedCount.sumThenReset();
        long lockFailed = lockFailCount.sumThenReset();
        long reconsumeLater = reconsumeLaterCount.sumThenReset();
        long delayedRetry = delayedRetryScheduledCount.sumThenReset();
        long success = completionSuccessCount.sumThenReset();
        long fail = completionFailCount.sumThenReset();
        long deadLetter = deadLetterCount.sumThenReset();
        long totalLatencyMs = completionLatencyTotalMs.sumThenReset();
        long maxLatencyMs = maxCompletionLatencyMs.getAndSet(0L);

        List<Long> samples = drainLatencySamples();
        long completed = success + fail;
        double avgLatencyMs = completed == 0 ? 0D : (double) totalLatencyMs / completed;

        log.info(
                "SECKILL_HEALTH windowSeconds=30 accepted={} success={} fail={} lockFail={} delayedRetry={} reconsumeLater={} deadLetter={} completionAvgMs={} completionMedianMs={} completionP95Ms={} completionMaxMs={}",
                accepted,
                success,
                fail,
                lockFailed,
                delayedRetry,
                reconsumeLater,
                deadLetter,
                String.format("%.2f", avgLatencyMs),
                percentile(samples, 50),
                percentile(samples, 95),
                maxLatencyMs
        );
    }

    private List<Long> drainLatencySamples() {
        List<Long> samples = new ArrayList<>();
        Long value;
        while ((value = completionLatencySamples.poll()) != null) {
            samples.add(value);
        }
        Collections.sort(samples);
        return samples;
    }

    private long percentile(List<Long> sortedValues, int percent) {
        if (sortedValues.isEmpty()) {
            return 0L;
        }
        int index = (int) Math.ceil(sortedValues.size() * percent / 100.0) - 1;
        index = Math.max(0, Math.min(index, sortedValues.size() - 1));
        return sortedValues.get(index);
    }
}
