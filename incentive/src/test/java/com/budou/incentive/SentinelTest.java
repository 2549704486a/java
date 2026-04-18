package com.budou.incentive;

import com.budou.incentive.controller.UserAwardController;
import com.budou.incentive.utils.Result;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;

import java.util.concurrent.CountDownLatch;

/**
 * @program: incentive
 * @description:
 * @author: 阿伟
 * @create: 2024-10-19 13:15
 **/
@SpringBootTest
public class SentinelTest {
    @Autowired
    UserAwardController userAwardController;

    @Test
    public void testConcurrentRequests() throws InterruptedException {
        int threadCount = 10;  // 模拟10个并发请求
        CountDownLatch latch = new CountDownLatch(threadCount);

        for (int i = 0; i < threadCount; i++) {
            final int userId = i;
            new Thread(() -> {
                try {
                    // 调用需要限流保护的方法
                    Result result = userAwardController.exchange((long) userId, 1L);
                    System.out.println(result);
                } finally {
                    latch.countDown();  // 每个线程完成后，countDown()
                }
            }).start();
        }

        latch.await();  // 等待所有线程执行完
    }

}
