package com.budou.incentive.service;

import com.budou.incentive.utils.Result;
import org.springframework.context.annotation.Bean;
import org.springframework.stereotype.Service;
import org.springframework.web.bind.annotation.RequestMapping;

@Service
public interface UserAwardService {
    Result exchange(Long userId, Long awardId);

    Result insert(Long userId, Long awardId);

    Result result(Long userId, Long awardId);
}
