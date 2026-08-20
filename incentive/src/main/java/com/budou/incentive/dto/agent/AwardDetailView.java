package com.budou.incentive.dto.agent;

import java.util.Date;

public record AwardDetailView(Long awardId,
                              String name,
                              String coverUrl,
                              Integer awardType,
                              Integer inventory,
                              Integer requiredPoints,
                              Date startTime,
                              Date endTime,
                              boolean overSellAllowed) {
}

