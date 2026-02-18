package com.budou.incentive.service;

import com.budou.incentive.dao.model.AwardInventorySplit;
import com.budou.incentive.dao.model.FinishTaskRecord;
import com.budou.incentive.dao.model.UserAward;
import com.budou.incentive.dao.model.UserCurrency;

public interface ConsumerService {
    void update1(Long id, Long userId, Long awardId, Integer price, Long splitId);

    void update2(Long id, Long userId, Long awardId, Integer currency);
}
