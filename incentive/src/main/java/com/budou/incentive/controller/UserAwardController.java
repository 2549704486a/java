package com.budou.incentive.controller;

import com.alibaba.csp.sentinel.annotation.SentinelResource;
import com.budou.incentive.dao.mapper.UserAwardMapper;
import com.budou.incentive.dao.model.UserAward;
import com.budou.incentive.service.UserAwardService;
import com.budou.incentive.utils.Result;
import com.budou.incentive.utils.SentinelUtil;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.*;

/**
 * @program: incentive-事务消息
 * @description:
 * @author: 阿伟
 * @create: 2024-10-05 11:29
 **/
@RestController
@RequestMapping("userAward")
public class UserAwardController {

    @Autowired
    private UserAwardMapper userAwardMapper;

    @Autowired
    private UserAwardService userAwardService;

    @RequestMapping(value="/query",method= RequestMethod.GET)
    public UserAward queryAward( // @RequestParam注解用于将请求参数绑定到方法参数上。
                                 // name="userId"指定了请求参数的名称。
                                 // Long userId是方法的参数，用于接收请求中的userId参数。
                                 @RequestParam(name = "userId") Long  userId,
                                 @RequestParam(name = "awardId") Long  awardId){
        // 调用userAwardMapper的selectUserAward方法，根据用户ID和奖励ID从数据库中查询用户奖励。
        UserAward userAward = userAwardMapper.selectUserAward(userId,awardId);
        System.out.println(userAward);
        return userAward;
    }

    @SentinelResource(value = "exchange", blockHandler = "handleException", blockHandlerClass = SentinelUtil.class)
    @GetMapping("exchange")
    public Result<?> exchange(@RequestParam(name = "userId") Long userId,
                              @RequestParam(name = "awardId") Long awardId) {
        return userAwardService.exchange(userId, awardId);
    }

    @GetMapping("result")
    public Result<?> result(@RequestParam(name = "userId") Long userId,
                             @RequestParam(name = "awardId") Long awardId){
        return userAwardService.result(userId, awardId);
    }
}
