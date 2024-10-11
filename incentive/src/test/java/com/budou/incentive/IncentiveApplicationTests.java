package com.budou.incentive;

import com.budou.incentive.dao.redis.RedisDao;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;

@SpringBootTest
class IncentiveApplicationTests {
    @Autowired
    RedisDao redisDao;

    @Test
    void contextLoads() {
        Object status = redisDao.hmGet("user_award:6:2", "status");
        if(status == null){
            System.out.println("yes");
        }else{
            System.out.println("no");
        }
    }

}
