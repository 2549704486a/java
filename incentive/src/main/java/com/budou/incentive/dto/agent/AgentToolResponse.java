package com.budou.incentive.dto.agent;

/**
 * Stable response envelope for Agent tools. The model should branch on code instead of parsing free-form messages.
 */
public record AgentToolResponse<T>(boolean success, String code, T data, String message, boolean retryable) {

    public static <T> AgentToolResponse<T> ok(String code, T data, String message) {
        return new AgentToolResponse<>(true, code, data, message, false);
    }

    public static <T> AgentToolResponse<T> fail(String code, String message, boolean retryable) {
        return new AgentToolResponse<>(false, code, null, message, retryable);
    }
}

