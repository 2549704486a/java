package com.budou.incentive;
import com.budou.incentive.infra.RedisLockWithRenewal;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
/**
 * @program: incentive
 * @description:
 * @author: 阿伟
 * @create: 2024-10-08 11:30
 **/
@SpringBootTest
public class DistributedLockTest {
    @Autowired
    RedisLockWithRenewal lockManager;
//    @Test
//    public  void Test1() {
//        String lockKey = "unique_lock_key";
//        String lockValue = "unique_lock_value"; // 唯一的锁标识，用于确认持有锁的线程
//
//        if (lockManager.acquireLock(lockKey, lockValue) != null) { // 尝试获取锁
//            try {
//                System.out.println("Lock acquired, performing task...");
//                // 模拟一个耗时的任务
//                Thread.sleep(10000);
//                System.out.println("Task completed");
//            } catch (InterruptedException e) {
//                e.printStackTrace(); // 处理异常
//            } finally {
//                lockManager.releaseLock(lockKey, lockValue, token); // 任务完成后释放锁
//                System.out.println("Lock released");
//            }
//        } else {
//            System.out.println("Could not acquire lock, task is already in progress by another process");
//        }
//    }
}
