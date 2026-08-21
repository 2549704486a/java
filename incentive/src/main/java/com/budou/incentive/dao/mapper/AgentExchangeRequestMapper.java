package com.budou.incentive.dao.mapper;

import com.budou.incentive.dao.model.AgentExchangeRequest;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;

@Mapper
public interface AgentExchangeRequestMapper {

    @Insert("insert into agent_exchange_request " +
            "(idempotency_key, request_fingerprint, user_id, award_id, status, create_time, update_time) " +
            "values (#{idempotencyKey}, #{requestFingerprint}, #{userId}, #{awardId}, #{status}, now(), now())")
    int insert(AgentExchangeRequest request);

    @Select("select id, idempotency_key as idempotencyKey, request_fingerprint as requestFingerprint, " +
            "user_id as userId, award_id as awardId, status, response_success as responseSuccess, " +
            "response_code as responseCode, response_message as responseMessage, " +
            "response_retryable as responseRetryable, create_time as createTime, update_time as updateTime " +
            "from agent_exchange_request where idempotency_key = #{idempotencyKey}")
    AgentExchangeRequest selectByIdempotencyKey(@Param("idempotencyKey") String idempotencyKey);

    @Update("update agent_exchange_request set status = 'COMPLETED', " +
            "response_success = #{success}, response_code = #{code}, response_message = #{message}, " +
            "response_retryable = #{retryable}, update_time = now() " +
            "where idempotency_key = #{idempotencyKey} and status = 'EXECUTING'")
    int complete(
            @Param("idempotencyKey") String idempotencyKey,
            @Param("success") boolean success,
            @Param("code") String code,
            @Param("message") String message,
            @Param("retryable") boolean retryable
    );

    @Update("update agent_exchange_request set status = 'UNKNOWN', " +
            "response_success = 0, response_code = 'SUBMISSION_UNKNOWN', " +
            "response_message = #{message}, response_retryable = 0, update_time = now() " +
            "where idempotency_key = #{idempotencyKey} and status = 'EXECUTING'")
    int markUnknown(
            @Param("idempotencyKey") String idempotencyKey,
            @Param("message") String message
    );
}
