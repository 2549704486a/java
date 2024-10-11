package com.budou.incentive.infra;

import com.budou.incentive.dao.redis.RedisDao;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Component;

import java.util.Arrays;
import java.util.Collections;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;

/**
 * @program: incentive
 * @description:
 * @author: 阿伟
 * @create: 2024-10-08 11:53
 **/
@Component
public class RedisLockWithRenewal {
    private final RedisDao redisDao;
    private final static Long EXPIRE_TIME = Long.valueOf(10);
    private final static int RENEWAL_INTERVAL = 5;
    private final static String FENCING_TOKEN_KEY = "fencing_token";
    //用于定期执行业务的线程池 "schedule"
    private final ScheduledExecutorService scheduler = Executors.newScheduledThreadPool(1);

    @Autowired
    public RedisLockWithRenewal(RedisDao redisDao){
        this.redisDao = redisDao;
        initToken();
    }

    private void initToken(){
        if(redisDao.get(FENCING_TOKEN_KEY) == null){
            redisDao.set(FENCING_TOKEN_KEY, 0);
        }
        System.out.println("RedisLockWithRenewal.acquireLock:初始化成功");
    }

    private Long getFencingToken(){
        return redisDao.increment(FENCING_TOKEN_KEY);
    }

    public Long acquireLock(String lockKey, String lockValue){
        if(redisDao.setnx(lockKey, lockValue, EXPIRE_TIME)){
            System.out.println("RedisLockWithRenewal.acquireLock:加锁成功");
            Long token = getFencingToken();
            startRenewalThread(lockKey, lockValue, token);
            return token;
        }
        System.out.println("RedisLockWithRenewal.acquireLock:加锁失败");
        return null;
    }

    private void startRenewalThread(String lockKey, String lockValue, Long token) {
        scheduler.scheduleAtFixedRate(() -> {
            //通过lua脚本保证get和expire两个操作的原子性，首先要保证KEYS[1]存在，否则get方法返回nil，导致lua脚本返回null
            //通过exist方法，保证lua脚本返回的结果一定是0或1。
            String Script = "if redis.call('exists', KEYS[1]) == 1 and redis.call('get', KEYS[1]) == ARGV[1] then " +
                            "   redis.call('expire', KEYS[1], ARGV[2]) " +
                            "   return 1 " +
                            "else " +
                            "   return 0 " +
                            "end";
            boolean result = redisDao.executeScript(Script, Arrays.asList(lockKey), lockValue, EXPIRE_TIME);
            if(result == false){
                scheduler.shutdown();
                return;
            }else{
                System.out.println("RedisLockWithRenewal.acquireLock:锁续期成功：" + EXPIRE_TIME + "秒");
            }
        },RENEWAL_INTERVAL, RENEWAL_INTERVAL, TimeUnit.SECONDS);
    }

    public void releaseLock(String lockKey, String lockValue){
        String result = (String) redisDao.get(lockKey);
        if(lockValue.equals(result)){
            redisDao.remove(lockKey);
            System.out.println("RedisLockWithRenewal.acquireLock:释放锁");
        }else{
            System.out.println("RedisLockWithRenewal.acquireLock:未持有锁");
        }
    }

    //直接判断exists(lockKey) && get(lockKey).equals(lockValue)不就行了？同时可以通过lua脚本保证原子性，就不需要token了
    public boolean isLatestToken(Long token){
        Long currentToken = Long.valueOf((Integer)redisDao.get(FENCING_TOKEN_KEY));
        System.out.println("RedisLockWithRenewal.acquireLock:token为" + token +
                "currentToken为：" + currentToken);
        if(token == currentToken){
            return true;
        } else{
            return false;
        }
    }
}
