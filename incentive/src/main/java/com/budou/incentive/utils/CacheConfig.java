package com.budou.incentive.utils;

import com.github.benmanes.caffeine.cache.Cache;
import com.github.benmanes.caffeine.cache.Caffeine;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

import java.util.Date;
import java.util.concurrent.TimeUnit;

@Configuration
public class CacheConfig {

    @Bean
    public Cache<Long, Integer> awardPriceCache() {
        return Caffeine.newBuilder()
                .maximumSize(1000)
                .expireAfterWrite(5, TimeUnit.MINUTES)
//                .refreshAfterWrite(3, TimeUnit.MINUTES)
                .build();
    }

    @Bean
    public Cache<Long, Date> awardEndTimeCache() {
        return Caffeine.newBuilder()
                .maximumSize(1000)
                .expireAfterWrite(5, TimeUnit.MINUTES)
//                .refreshAfterWrite(3, TimeUnit.MINUTES)
                .build();
    }

    @Bean
    public Cache<Long, Date> awardStartTimeCache() {
        return Caffeine.newBuilder()
                .maximumSize(1000)
                .expireAfterWrite(5, TimeUnit.MINUTES)
                .build();
    }

    @Bean
    public Cache<Long, Integer> awardIsOverSellCache() {
        return Caffeine.newBuilder()
                .maximumSize(1000)
                .expireAfterWrite(5, TimeUnit.MINUTES)
//                .refreshAfterWrite(3, TimeUnit.MINUTES)
                .build();
    }

    @Bean
    public Cache<Long, Integer> userCurrencyCache() {
        return Caffeine.newBuilder()
                .maximumSize(10000)
                .expireAfterWrite(1, TimeUnit.MINUTES)
                .build();
    }

    @Bean
    public Cache<String, Integer> idempotentCache() {
        return Caffeine.newBuilder()
                .maximumSize(10000)
                .expireAfterWrite(24, TimeUnit.HOURS)
                .build();
    }

}
