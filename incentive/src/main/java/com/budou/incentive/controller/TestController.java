package com.budou.incentive.controller;

import com.budou.incentive.dao.mapper.AwardConfigMapper;
import com.budou.incentive.dao.mapper.UserAwardMapper;
import com.budou.incentive.dao.mapper.UserCurrencyMapper;
import com.budou.incentive.dao.redis.RedisDao;
import com.budou.incentive.service.AwardService;
import com.budou.incentive.service.TransactionService;
import com.budou.incentive.infra.TransactionProducer;
import com.budou.incentive.service.UserAwardService;
import com.budou.incentive.utils.Result;
import org.apache.rocketmq.spring.core.RocketMQTemplate;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.*;

import static java.time.LocalTime.now;

// 定义一个控制器类，用于处理Web请求
@RestController
@RequestMapping("test")
public class TestController {

    @Autowired
    private TransactionService transactionService;

    @Autowired
    private UserCurrencyMapper userCurrencyMapper;

    @Autowired
    private AwardConfigMapper awardConfigMapper;

    @Autowired
    private AwardService awardService;

    // 自动注入UserAwardMapper实例，用于数据库操作
    @Autowired
    private UserAwardMapper userAwardMapper;

    @Autowired
    private UserAwardService userAwardService;
    // 自动注入RedisDao实例，用于Redis操作
    @Autowired
    private RedisDao redisDao;

    @Autowired
    private RocketMQTemplate rocketMQTemplate;

    // 自动注入TransactionProducer实例，用于处理消息队列事务
    @Autowired
    private TransactionProducer transactionProducer;


    @RequestMapping(value="/redis/set",method= RequestMethod.GET)
    public boolean setRedisKV(@RequestParam(name = "key") String  key,
                              @RequestParam(name = "value") String  value){
        boolean flg = redisDao.set(key,value);
        return flg;
    }

    @RequestMapping(value="/redis/get",method= RequestMethod.GET)
    public Object getRedisKV(@RequestParam(name = "key") String  key){
        Object value = redisDao.get(key);
//        System.out.println(value);
//        System.out.println(userMapper.selectUserInfo(Long.parseLong(key)));
        return value;
    }

    @RequestMapping(value="/api/send/transaction/message",method= RequestMethod.GET)
    //定义了一个返回类型为String的公开方法sendTransaction，用于处理/api/send/transaction/message路径的GET请求。
    public Result sendTransaction(@RequestParam(name = "message") String  message,
                                  @RequestParam(name = "id") String  id){
        return transactionService.sendTransaction(message, id);
    }
}
