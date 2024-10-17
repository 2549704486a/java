package com.budou.incentive.service.impl;

import com.budou.incentive.dao.model.FinishTaskRecord;
import com.budou.incentive.service.TransactionService;
import com.budou.incentive.infra.TransactionProducer;
import com.budou.incentive.utils.Result;
import com.budou.incentive.utils.ResultCodeEnum;
import jakarta.transaction.Transactional;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

/**
 * @program: incentive-事务消息
 * @description:
 * @author: 阿伟
 * @create: 2024-09-29 21:33
 **/
@Service
public class TransactionServiceImpl implements TransactionService {

    @Autowired
    private TransactionProducer transactionProducer;

    @Override
    public Result sendTransaction(String message, String id) {
        try{
            System.out.println("TransactionServiceImpl.sendTransaction：正在发送事务消息...");
            return transactionProducer.sendTransactionMessage(id, message);
        }catch (Exception e){
            System.out.println(e);
            return Result.build(null, ResultCodeEnum.TRANSACTION_SEND_FAILED);
        }
    }
}
