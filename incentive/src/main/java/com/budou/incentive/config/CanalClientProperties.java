package com.budou.incentive.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties(prefix = "canal.client")
public class CanalClientProperties {
    private boolean enabled = true;
    private String host = "localhost";
    private int port = 11111;
    private String destination = "example";
    private String username = "canal";
    private String password = "canal";
    private String subscribePattern = ".*\\.*";
    private int batchSize = 200;
    private long idleDelayMs = 2000L;
    private long retryIntervalMs = 10000L;

    public boolean isEnabled() {
        return enabled;
    }

    public void setEnabled(boolean enabled) {
        this.enabled = enabled;
    }

    public String getHost() {
        return host;
    }

    public void setHost(String host) {
        this.host = host;
    }

    public int getPort() {
        return port;
    }

    public void setPort(int port) {
        this.port = port;
    }

    public String getDestination() {
        return destination;
    }

    public void setDestination(String destination) {
        this.destination = destination;
    }

    public String getUsername() {
        return username;
    }

    public void setUsername(String username) {
        this.username = username;
    }

    public String getPassword() {
        return password;
    }

    public void setPassword(String password) {
        this.password = password;
    }

    public String getSubscribePattern() {
        return subscribePattern;
    }

    public void setSubscribePattern(String subscribePattern) {
        this.subscribePattern = subscribePattern;
    }

    public int getBatchSize() {
        return batchSize;
    }

    public void setBatchSize(int batchSize) {
        this.batchSize = batchSize;
    }

    public long getIdleDelayMs() {
        return idleDelayMs;
    }

    public void setIdleDelayMs(long idleDelayMs) {
        this.idleDelayMs = idleDelayMs;
    }

    public long getRetryIntervalMs() {
        return retryIntervalMs;
    }

    public void setRetryIntervalMs(long retryIntervalMs) {
        this.retryIntervalMs = retryIntervalMs;
    }
}
