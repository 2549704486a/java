-- Agent 运行数据看板事实表：只保存请求与 Tool 摘要，不保存对话或身份正文。
USE `budou`;

CREATE TABLE IF NOT EXISTS `agent_request_observation` (
  `request_id` varchar(128) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  `agent_type` varchar(16) CHARACTER SET ascii COLLATE ascii_bin NOT NULL COMMENT 'USER/OPERATOR',
  `started_at` datetime(3) NOT NULL COMMENT 'UTC 请求开始时间',
  `completed_at` datetime(3) NOT NULL COMMENT 'UTC 请求结束时间',
  `status` varchar(16) CHARACTER SET ascii COLLATE ascii_bin NOT NULL COMMENT 'COMPLETED/FAILED',
  `elapsed_ms` bigint unsigned NOT NULL,
  `model_call_count` int unsigned NOT NULL DEFAULT 0,
  `input_tokens` bigint unsigned DEFAULT NULL,
  `output_tokens` bigint unsigned DEFAULT NULL,
  `tool_call_count` int unsigned NOT NULL DEFAULT 0,
  `error_type` varchar(128) DEFAULT NULL COMMENT '脱敏后的错误类型',
  `created_at` timestamp(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  PRIMARY KEY (`request_id`),
  KEY `idx_agent_request_started` (`started_at`),
  KEY `idx_agent_request_type_started` (`agent_type`, `started_at`),
  KEY `idx_agent_request_status_started` (`status`, `started_at`),
  CONSTRAINT `chk_agent_request_type` CHECK (`agent_type` IN ('USER', 'OPERATOR')),
  CONSTRAINT `chk_agent_request_status` CHECK (`status` IN ('COMPLETED', 'FAILED')),
  CONSTRAINT `chk_agent_request_time` CHECK (`completed_at` >= `started_at`),
  CONSTRAINT `chk_agent_request_tokens` CHECK (
    (`input_tokens` IS NULL AND `output_tokens` IS NULL)
    OR (`input_tokens` IS NOT NULL AND `output_tokens` IS NOT NULL)
  )
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='Agent 请求运行摘要';

CREATE TABLE IF NOT EXISTS `agent_tool_observation` (
  `request_id` varchar(128) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  `sequence` int unsigned NOT NULL,
  `tool_name` varchar(128) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  `transport` varchar(32) CHARACTER SET ascii COLLATE ascii_bin DEFAULT NULL,
  `completed` tinyint(1) NOT NULL,
  `business_success` tinyint(1) NOT NULL,
  `result_code` varchar(64) CHARACTER SET ascii COLLATE ascii_bin DEFAULT NULL,
  `elapsed_ms` bigint unsigned NOT NULL,
  `error_type` varchar(128) DEFAULT NULL COMMENT '脱敏后的错误类型',
  `created_at` timestamp(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  PRIMARY KEY (`request_id`, `sequence`),
  KEY `idx_agent_tool_name` (`tool_name`),
  CONSTRAINT `fk_agent_tool_request`
    FOREIGN KEY (`request_id`) REFERENCES `agent_request_observation` (`request_id`)
    ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='Agent Tool 调用摘要';
