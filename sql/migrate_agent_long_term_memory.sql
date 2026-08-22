-- Agent 长期记忆第一阶段：原文优先、增量更新、保留失效历史。
USE `budou`;

CREATE TABLE IF NOT EXISTS `agent_long_term_memory` (
  `memory_id` char(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  `user_id` bigint NOT NULL,
  `memory_type` varchar(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  `memory_key` varchar(255) NOT NULL COMMENT '可读的记忆身份键，用于识别同一主题',
  `active_key` varchar(255) DEFAULT NULL COMMENT '仅生效记录保留，用于保证同主题唯一',
  `raw_text` varchar(500) NOT NULL COMMENT '忠实保存用户原始表达',
  `normalized_data` json NOT NULL COMMENT '可选的结构化投影，不作为保存前置条件',
  `status` varchar(16) CHARACTER SET ascii COLLATE ascii_bin NOT NULL COMMENT 'ACTIVE/SUPERSEDED/DELETED',
  `valid_from` datetime(3) DEFAULT NULL,
  `valid_to` datetime(3) DEFAULT NULL,
  `source_session` varchar(128) NOT NULL,
  `source_message_id` varchar(128) DEFAULT NULL,
  `created_at` datetime(3) NOT NULL,
  `updated_at` datetime(3) NOT NULL,
  PRIMARY KEY (`memory_id`),
  UNIQUE KEY `uk_agent_memory_active` (`user_id`, `active_key`),
  KEY `idx_agent_memory_user_type_status` (`user_id`, `memory_type`, `status`),
  KEY `idx_agent_memory_user_updated` (`user_id`, `updated_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='Agent 用户长期记忆';
