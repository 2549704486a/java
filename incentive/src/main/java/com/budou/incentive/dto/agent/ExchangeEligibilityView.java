package com.budou.incentive.dto.agent;

public record ExchangeEligibilityView(Long userId,
                                      Long awardId,
                                      boolean eligible,
                                      String reasonCode,
                                      String reason,
                                      Integer currentPoints,
                                      Integer requiredPoints,
                                      Integer pointsGap) {
}

