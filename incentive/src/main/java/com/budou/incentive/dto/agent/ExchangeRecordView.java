package com.budou.incentive.dto.agent;

import java.util.Date;

public record ExchangeRecordView(
        Long orderId,
        Long awardId,
        String awardName,
        String status,
        String statusMessage,
        Date createTime,
        Date updateTime
) {
}
