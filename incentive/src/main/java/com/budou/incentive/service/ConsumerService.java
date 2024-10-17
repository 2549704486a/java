package com.budou.incentive.service;

import com.budou.incentive.dao.model.AwardInventorySplit;
import com.budou.incentive.dao.model.FinishTaskRecord;
import com.budou.incentive.dao.model.UserAward;
import com.budou.incentive.dao.model.UserCurrency;

public interface ConsumerService {
    void update1(AwardInventorySplit awardInventorySplit, UserCurrency userCurrency,
                 UserAward userAward, String lockKey, String lockValue);

    void update2(UserCurrency userCurrency, UserAward userAward);
}
