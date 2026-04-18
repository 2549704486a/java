package com.budou.incentive.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

import java.util.ArrayList;
import java.util.List;

@ConfigurationProperties(prefix = "cache.warm")
public class CacheWarmProperties {
    private boolean enabled = true;
    private List<Long> awardIds = new ArrayList<>(List.of(6L));

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
}
