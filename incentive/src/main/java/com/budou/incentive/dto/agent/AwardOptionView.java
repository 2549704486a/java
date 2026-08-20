package com.budou.incentive.dto.agent;

public record AwardOptionView(AwardDetailView award,
                              boolean redeemable,
                              Integer pointsGap,
                              String reasonCode) {
}

