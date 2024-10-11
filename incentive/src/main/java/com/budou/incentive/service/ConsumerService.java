package com.budou.incentive.service;

import com.budou.incentive.dao.model.AwardConfig;
import com.budou.incentive.dao.model.AwardInventorySplit;
import com.budou.incentive.dao.model.UserAward;
import com.budou.incentive.dao.model.UserCurrency;

public interface ConsumerService {
    void update1(AwardConfig awardConfig, AwardInventorySplit awardInventorySplit, UserCurrency userCurrency,
                 UserAward userAward, String lockKey, String lockValue, Long token);

    void update2(UserCurrency userCurrency, UserAward userAward);
}
