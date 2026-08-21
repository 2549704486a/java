package com.budou.incentive.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

import java.util.ArrayList;
import java.util.List;

@ConfigurationProperties(prefix = "cache.warm")
public class CacheWarmProperties {
    private boolean enabled = true;
    private List<Long> awardIds = new ArrayList<>(List.of(1L, 2L, 3L, 4L, 5L, 6L));
    private boolean userCurrencyEnabled = true;
    private Long userCurrencyMinUserId = 1L;
    private Long userCurrencyMaxUserId = 10000L;

    public boolean isEnabled() {
        return enabled;
    }

    public void setEnabled(boolean enabled) {
        this.enabled = enabled;
    }

    public List<Long> getAwardIds() {
        return awardIds;
    }

    public void setAwardIds(List<Long> awardIds) {
        this.awardIds = awardIds;
    }

    public boolean isUserCurrencyEnabled() {
        return userCurrencyEnabled;
    }

    public void setUserCurrencyEnabled(boolean userCurrencyEnabled) {
        this.userCurrencyEnabled = userCurrencyEnabled;
    }

    public Long getUserCurrencyMinUserId() {
        return userCurrencyMinUserId;
    }

    public void setUserCurrencyMinUserId(Long userCurrencyMinUserId) {
        this.userCurrencyMinUserId = userCurrencyMinUserId;
    }

    public Long getUserCurrencyMaxUserId() {
        return userCurrencyMaxUserId;
    }

    public void setUserCurrencyMaxUserId(Long userCurrencyMaxUserId) {
        this.userCurrencyMaxUserId = userCurrencyMaxUserId;
    }
}
