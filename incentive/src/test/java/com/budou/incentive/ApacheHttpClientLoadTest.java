package com.budou.incentive;

import org.apache.hc.client5.http.impl.classic.CloseableHttpClient;
import org.apache.hc.client5.http.impl.classic.CloseableHttpResponse;
import org.apache.hc.client5.http.impl.classic.HttpClients;
import org.apache.hc.client5.http.classic.methods.HttpGet;

import java.io.IOException;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;

public class ApacheHttpClientLoadTest {
    public static void main(String[] args) throws InterruptedException, IOException {
        int totalRequests = 1000; // 总请求数
        int concurrentThreads = 10; // 并发线程数

        // 创建一个固定大小的线程池
        ExecutorService executorService = Executors.newFixedThreadPool(concurrentThreads);

        // 使用 Apache HttpClient 创建一个可关闭的 HttpClient 实例
        CloseableHttpClient client = HttpClients.createDefault();
        long startTime = System.currentTimeMillis();
        try {
            // 循环遍历，总共发起 totalRequests 个请求
            for (int i = 1; i <= totalRequests; i++) {
                int finalI = i;
                executorService.submit(() -> { // 将每个请求提交到线程池中执行
                    long requestStartTime = System.currentTimeMillis();
                    try {
                        // 创建一个 HTTP GET 请求对象
                        HttpGet request = new HttpGet("http://localhost:8088/userAward/exchange?userId="
                                + finalI + "&awardId=6");

                        // 执行 HTTP 请求并获取响应
                        try (CloseableHttpResponse response = client.execute(request)) {
                            long responseTime = System.currentTimeMillis() - requestStartTime;
                            // 打印响应状态码到控制台
                            System.out.println("Response code: " + response.getCode() + ", Response time: " + responseTime + " ms");
                        }
                    } catch (Exception e) {
                        e.printStackTrace(); // 捕获并打印异常信息
                    }
                });
            }
        } catch (Exception e) {
            e.printStackTrace(); // 捕获并打印异常信息
        } finally {
            // 关闭线程池，等待所有任务完成后终止
            executorService.shutdown();
            executorService.awaitTermination(2, TimeUnit.MINUTES); // 等待线程池在 1 分钟内完成所有任务

            // 关闭 HttpClient
            client.close();
        }
        long totalTime = System.currentTimeMillis() - startTime; // 计算总时间
        double qps = (double) totalRequests / (totalTime / 1000); // 计算 QPS
        System.out.println("Total requests: " + totalRequests);
        System.out.println("Total time: " + totalTime + " ms");
        System.out.printf("QPS: %.2f requests per second%n", qps);
    }
}
