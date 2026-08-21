package com.budou.incentive.dao.model;

import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.util.Date;

/**
 * Agent 兑换请求的持久化幂等记录，与消费成功后的业务幂等记录分开保存。
 */
@Data
@NoArgsConstructor
@AllArgsConstructor
public class AgentExchangeRequest {
    private Long id;
    private String idempotencyKey;
    private String requestFingerprint;
    private Long userId;
    private Long awardId;
    private String status;
    private Boolean responseSuccess;
    private String responseCode;
    private String responseMessage;
    private Boolean responseRetryable;
    private Date createTime;
    private Date updateTime;
}
