package com.budou.incentive.service;

import com.budou.incentive.utils.Result;


public interface UserAwardService {
    Result exchange(Long userId, Long awardId);

    Result insert(Long userId, Long awardId);

    Result result(Long userId, Long awardId);
}
