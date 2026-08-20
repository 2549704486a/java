package com.budou.incentive.dto.agent;

import java.util.Date;

public record TaskOptionView(Long taskId,
                             String taskName,
                             Integer rewardPoints,
                             Date startTime,
                             Date endTime,
                             Integer type,
                             String description,
                             String status) {
}

