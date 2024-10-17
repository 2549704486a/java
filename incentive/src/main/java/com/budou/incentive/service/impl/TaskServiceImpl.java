package com.budou.incentive.service.impl;

import com.budou.incentive.dao.mapper.*;
import com.budou.incentive.dao.model.AddCurrencyRecord;
import com.budou.incentive.dao.model.FinishTaskRecord;
import com.budou.incentive.dao.model.TaskConfig;
import com.budou.incentive.dao.model.UserCurrency;
import com.budou.incentive.service.TaskService;
import com.budou.incentive.utils.Result;
import com.budou.incentive.utils.SpringBeanUtil;
import jakarta.transaction.Transactional;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

import java.util.Date;

/**
 * @program: incentive
 * @description:
 * @author: 阿伟
 * @create: 2024-10-16 16:17
 **/
@Service
public class TaskServiceImpl implements TaskService {
    @Autowired
    private UserCurrencyMapper userCurrencyMapper;
    @Autowired
    private AddCurrencyRecordMapper addCurrencyRecordMapper;
    @Autowired
    private TaskConfigMapper taskConfigMapper;
    @Autowired
    private UserTaskMapper userTaskMapper;
    @Autowired
    private FinishTaskRecordMapper finishTaskRecordMapper;
    @Override
    public Result finish(Long userId, Long taskId) {
        //判断用户Id、任务Id、任务有效期的合法性
        UserCurrency userCurrency = userCurrencyMapper.selectUserInfo(userId);
        if(userCurrency == null){
            return Result.fail("用户不存在");
        }
        TaskConfig taskConfig = taskConfigMapper.selectTask(taskId);
        if(taskConfig == null){
            return Result.fail("任务不存在");
        }
        Date targetTime = new Date();
        if(!(targetTime.after(taskConfig.getStartTime()) && targetTime.before(taskConfig.getEndTime()))){
            return Result.fail("任务未开始或已结束");
        }

        //执行完成任务的业务操作
        Integer rows = 0;
        FinishTaskRecord finishTaskRecord = new FinishTaskRecord(null, userId, taskId, 0, new Date());
        TaskService bean = SpringBeanUtil.getBean(TaskService.class);
        try{
            rows = bean.finishTransaction(finishTaskRecord, userId);
        }catch (Exception e){
            System.out.println("TaskServiceImpl.finish:" + e.getMessage());
            return Result.fail("事务执行失败");
        }
        if ((rows) == 2) {
            System.out.println("TaskServiceImpl.finish:执行成功");
            return Result.ok("任务完成");
        } else {
            return Result.fail("执行失败");
        }
    }

    @Override
    public Result reward(Long userId, Long taskId) {
        //判断用户Id、任务Id的合法性
        UserCurrency userCurrency = userCurrencyMapper.selectUserInfo(userId);
        if(userCurrency == null){
            return Result.fail("用户不存在");
        }
        TaskConfig taskConfig = taskConfigMapper.selectTask(taskId);
        if(taskConfig == null){
            return Result.fail("任务不存在");
        }

        //判断任务奖励是否已领取
        Integer status = finishTaskRecordMapper.selectTaskStatus(userId, taskId);
        if(status == null) {
            return Result.fail("任务未完成");
        }
        if(status == 1){
            return Result.fail("积分已领取");
        }

        //如果未领取，执行领取事务
        if(status == 0){
            TaskService bean = SpringBeanUtil.getBean(TaskService.class);
            try{
                bean.rewardTransaction(userId, taskId);
            }catch (Exception e){
                System.out.println("TaskServiceImpl.reward:" + e.getMessage());
                return Result.fail("领取失败");
            }
        }
        return Result.ok("领取成功");
    }

    //完成任务的事务方法
    @Override
    @Transactional
    public void rewardTransaction(Long userId, Long taskId) {
        Integer row = finishTaskRecordMapper.updateTaskStatus(userId, taskId);
        if(row == 0){
            throw new RuntimeException("任务状态更新失败");
        }
        Integer beforeCurrency = userCurrencyMapper.selectCurrency(userId);
        Integer currency = taskConfigMapper.getTaskCurrency(taskId);
        AddCurrencyRecord addCurrencyRecord = new AddCurrencyRecord(null, userId, currency,
                beforeCurrency + currency, userId.toString() + ":" + taskId.toString(),
                "完成任务", new Date());
        addCurrencyRecordMapper.insert(addCurrencyRecord);
        userCurrencyMapper.addCurrency(userId, currency);
    }

    //领取奖励的事务方法
    @Override
    @Transactional
    public Integer finishTransaction(FinishTaskRecord finishTaskRecord, Long userId) {
        int rows1 = finishTaskRecordMapper.insertFinishTask(finishTaskRecord);
        int rows2 = userTaskMapper.updateCompletedTasks(userId);
        return rows1 + rows2;
    }
}
