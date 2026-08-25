package com.budou.incentive.dto.agent;

import java.math.BigDecimal;

public record CampaignGroupFunnelView(
        String experimentGroup,
        int targetedUsers,
        int deliveredUsers,
        int viewedUsers,
        int clickedUsers,
        int taskCompletedUsers,
        int exchangedUsers,
        BigDecimal deliveryRate,
        BigDecimal viewRate,
        BigDecimal clickRate,
        BigDecimal taskCompletionRate,
        BigDecimal exchangeRate
) {
}
