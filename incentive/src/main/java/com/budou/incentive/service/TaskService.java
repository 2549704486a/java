package com.budou.incentive.service;

import com.budou.incentive.dao.model.FinishTaskRecord;
import com.budou.incentive.utils.Result;

public interface TaskService {
    Result finish(Long userId, Long taskId);

    Integer finishTransaction(FinishTaskRecord finishTaskRecord, Long userId);

    Result reward(Long userId, Long taskId);

    void rewardTransaction(Long userId, Long taskId);
}
