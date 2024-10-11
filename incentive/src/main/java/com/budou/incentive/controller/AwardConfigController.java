package com.budou.incentive.controller;

import com.budou.incentive.dao.mapper.AwardConfigMapper;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * @program: incentive-事务消息
 * @description:
 * @author: 阿伟
 * @create: 2024-10-05 11:25
 **/

@RestController
@RequestMapping("awardConfig")
public class AwardConfigController {

    @Autowired
    private AwardConfigMapper awardConfigMapper;

//    @RequestMapping("insert")
//    public Result insert(){
//        Award award = new Award(Long.valueOf(4), "111", "耳机", 1, 1000,
//                30, new Date().getTime(), new Date().getTime() + 24 * 60 * 60 * 1000,
//                new Date(), new Date(), 1000 );
//        awardMapper.insert(award);
//        return Result.ok(award);
//    }
}
