package com.budou.incentive.controller;

import com.budou.incentive.service.TaskService;
import com.budou.incentive.utils.Result;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * @program: incentive
 * @description:
 * @author: 阿伟
 * @create: 2024-10-15 22:30
 **/
@RestController
@RequestMapping("task")
public class TaskController {
    @Autowired
    private TaskService taskService;

    @GetMapping("finish")
    public Result finish(Long userId, Long taskId){
        Result result = taskService.finish(userId, taskId);
        return result;
    }

    @GetMapping("reward")
    public Result reward(Long userId, Long taskId){
        Result result = taskService.reward(userId, taskId);
        return result;
    }
}
