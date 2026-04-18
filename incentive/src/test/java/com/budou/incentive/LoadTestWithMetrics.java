package com.budou.incentive;

import org.apache.hc.client5.http.impl.classic.CloseableHttpClient;
import org.apache.hc.client5.http.impl.classic.CloseableHttpResponse;
import org.apache.hc.client5.http.impl.classic.HttpClients;
import org.apache.hc.client5.http.classic.methods.HttpGet;
import org.junit.jupiter.api.Test;

import java.io.IOException;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicLong;

/**
 * 高性能压测工具 - 支持详细统计指标
 * 用于对比测试本地缓存优化前后的性能差异
 */
public class LoadTestWithMetrics {

    // 测试配置参数
    private static final String BASE_URL = "http://localhost:8088";
    private static final int AWARD_ID = 6;
    
    // 统计指标
    private final List<Long> responseTimes = Collections.synchronizedList(new ArrayList<>());
    private final AtomicInteger successCount = new AtomicInteger(0);
    private final AtomicInteger failCount = new AtomicInteger(0);
    private final AtomicLong totalBytes = new AtomicLong(0);

    /**
     * 主方法 - 执行压测
     * 可以通过修改参数来测试不同并发级别
     */
    public static void main(String[] args) throws Exception {
        LoadTestWithMetrics tester = new LoadTestWithMetrics();
        
        System.out.println("========================================");
        System.out.println("      兑换奖品接口压测工具");
        System.out.println("========================================\n");
        
        // 测试场景1: 低并发
        System.out.println("【测试场景1】低并发测试 - 10线程, 1000请求");
        tester.runTest(1000, 10, 5);
        
        Thread.sleep(2000); // 间隔2秒
        
        // 测试场景2: 中并发
        System.out.println("\n【测试场景2】中并发测试 - 50线程, 5000请求");
        tester.runTest(5000, 50, 10);
        
        Thread.sleep(2000); // 间隔2秒
        
        // 测试场景3: 高并发
        System.out.println("\n【测试场景3】高并发测试 - 100线程, 10000请求");
        tester.runTest(10000, 100, 20);
        
        System.out.println("\n========================================");
        System.out.println("           所有测试完成!");
        System.out.println("========================================");
    }

    /**
     * 执行压测
     * @param totalRequests 总请求数
     * @param concurrentThreads 并发线程数
     * @param rampUpSeconds 启动时间（秒）
     */
    public void runTest(int totalRequests, int concurrentThreads, int rampUpSeconds) throws Exception {
        // 重置统计数据
        responseTimes.clear();
        successCount.set(0);
        failCount.set(0);
        totalBytes.set(0);
        
        ExecutorService executorService = Executors.newFixedThreadPool(concurrentThreads);
        CloseableHttpClient client = HttpClients.createDefault();
        CountDownLatch latch = new CountDownLatch(totalRequests);
        
        long testStartTime = System.currentTimeMillis();
        
        // 计算每个线程的请求数和启动延迟
        int requestsPerThread = totalRequests / concurrentThreads;
        long rampUpIntervalMs = (rampUpSeconds * 1000L) / concurrentThreads;
        
        try {
            for (int threadIndex = 0; threadIndex < concurrentThreads; threadIndex++) {
                final int threadId = threadIndex;
                
                // 模拟 Ramp-Up 时间
                Thread.sleep(rampUpIntervalMs);
                
                executorService.submit(() -> {
                    for (int i = 0; i < requestsPerThread; i++) {
                        int userId = threadId * requestsPerThread + i + 1;
                        executeRequest(client, userId);
                        latch.countDown();
                    }
                });
            }
            
            // 等待所有请求完成
            latch.await(10, TimeUnit.MINUTES);
            
        } finally {
            executorService.shutdown();
            executorService.awaitTermination(2, TimeUnit.MINUTES);
            client.close();
        }
        
        long testEndTime = System.currentTimeMillis();
        printMetrics(totalRequests, testEndTime - testStartTime);
    }

    /**
     * 执行单个请求
     */
    private void executeRequest(CloseableHttpClient client, int userId) {
        long requestStartTime = System.currentTimeMillis();
        String url = BASE_URL + "/userAward/exchange?userId=" + userId + "&awardId=" + AWARD_ID;
        
        try {
            HttpGet request = new HttpGet(url);
            
            try (CloseableHttpResponse response = client.execute(request)) {
                long responseTime = System.currentTimeMillis() - requestStartTime;
                int statusCode = response.getCode();
                
                responseTimes.add(responseTime);
                
                if (statusCode == 200) {
                    successCount.incrementAndGet();
                } else {
                    failCount.incrementAndGet();
                }
                
                // 统计响应体大小
                if (response.getEntity() != null) {
                    totalBytes.addAndGet(response.getEntity().getContentLength());
                }
            }
        } catch (Exception e) {
            responseTimes.add(System.currentTimeMillis() - requestStartTime);
            failCount.incrementAndGet();
        }
    }

    /**
     * 打印压测指标
     */
    private void printMetrics(int totalRequests, long totalTimeMs) {
        double totalTimeSec = totalTimeMs / 1000.0;
        double qps = totalRequests / totalTimeSec;
        
        // 计算响应时间统计
        List<Long> sortedTimes = new ArrayList<>(responseTimes);
        Collections.sort(sortedTimes);
        
        long minTime = sortedTimes.isEmpty() ? 0 : sortedTimes.get(0);
        long maxTime = sortedTimes.isEmpty() ? 0 : sortedTimes.get(sortedTimes.size() - 1);
        double avgTime = sortedTimes.stream().mapToLong(Long::longValue).average().orElse(0);
        
        long p50 = getPercentile(sortedTimes, 50);
        long p90 = getPercentile(sortedTimes, 90);
        long p95 = getPercentile(sortedTimes, 95);
        long p99 = getPercentile(sortedTimes, 99);
        
        double successRate = (double) successCount.get() / totalRequests * 100;
        double throughputKB = totalBytes.get() / 1024.0 / totalTimeSec;
        
        System.out.println("┌─────────────────────────────────────────┐");
        System.out.println("│           压测结果统计                   │");
        System.out.println("├─────────────────────────────────────────┤");
        System.out.printf("│ 总请求数:        %6d                 │%n", totalRequests);
        System.out.printf("│ 成功请求:        %6d (%.2f%%)         │%n", successCount.get(), successRate);
        System.out.printf("│ 失败请求:        %6d                 │%n", failCount.get());
        System.out.printf("│ 总耗时:          %6.2f 秒              │%n", totalTimeSec);
        System.out.printf("│ QPS:             %6.2f                │%n", qps);
        System.out.printf("│ 吞吐量:          %6.2f KB/s           │%n", throughputKB);
        System.out.println("├─────────────────────────────────────────┤");
        System.out.println("│           响应时间统计 (ms)              │");
        System.out.println("├─────────────────────────────────────────┤");
        System.out.printf("│ 最小值:          %6d                 │%n", minTime);
        System.out.printf("│ 平均值:          %6.2f                │%n", avgTime);
        System.out.printf("│ 最大值:          %6d                 │%n", maxTime);
        System.out.printf("│ P50:             %6d                 │%n", p50);
        System.out.printf("│ P90:             %6d                 │%n", p90);
        System.out.printf("│ P95:             %6d                 │%n", p95);
        System.out.printf("│ P99:             %6d                 │%n", p99);
        System.out.println("└─────────────────────────────────────────┘");
    }

    /**
     * 获取百分位数
     */
    private long getPercentile(List<Long> sortedList, int percentile) {
        if (sortedList.isEmpty()) return 0;
        int index = (int) Math.ceil(percentile / 100.0 * sortedList.size()) - 1;
        return sortedList.get(Math.max(0, index));
    }

    /**
     * JUnit 测试方法 - 快速测试
     */
    @Test
    public void quickTest() throws Exception {
        System.out.println("快速压测测试...");
        runTest(100, 10, 2);
    }
}
