package com.budou.incentive.service;

import com.budou.incentive.utils.Result;

public interface TransactionService {
    Result sendTransaction(String  message, String  id);
}
