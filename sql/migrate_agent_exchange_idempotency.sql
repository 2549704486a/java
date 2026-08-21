-- Agent 兑换写入口的请求级幂等记录。
-- 该表记录“是否执行过这次 HTTP 写请求”，不替代消费侧 idempotent_table。
USE `budou`;

CREATE TABLE IF NOT EXISTS `agent_exchange_request` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `idempotency_key` varchar(128) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  `request_fingerprint` char(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  `user_id` bigint NOT NULL,
  `award_id` bigint NOT NULL,
  `status` varchar(16) CHARACTER SET ascii COLLATE ascii_bin NOT NULL COMMENT 'EXECUTING/COMPLETED/UNKNOWN',
  `response_success` tinyint(1) DEFAULT NULL,
  `response_code` varchar(64) CHARACTER SET ascii COLLATE ascii_bin DEFAULT NULL,
  `response_message` varchar(255) DEFAULT NULL,
  `response_retryable` tinyint(1) DEFAULT NULL,
  `create_time` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `update_time` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_agent_exchange_idempotency_key` (`idempotency_key`),
  KEY `idx_agent_exchange_user_award` (`user_id`, `award_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='Agent exchange request idempotency table';
