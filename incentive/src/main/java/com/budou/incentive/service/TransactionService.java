package com.budou.incentive.service;

import com.budou.incentive.utils.Result;
import org.springframework.web.bind.annotation.RequestParam;

public interface TransactionService {
    public Result sendTransaction(String  message, String  id);
}
