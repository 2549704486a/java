USE `budou`;

CREATE TABLE IF NOT EXISTS `user_activity_summary` (
  `user_id` BIGINT NOT NULL,
  `last_login_at` DATETIME(3) NULL,
  `last_active_at` DATETIME(3) NULL,
  `source` VARCHAR(16) CHARACTER SET ascii COLLATE ascii_bin NOT NULL COMMENT 'REAL/FIXTURE',
  `created_at` DATETIME(3) NOT NULL,
  `updated_at` DATETIME(3) NOT NULL,
  PRIMARY KEY (`user_id`),
  KEY `idx_user_activity_last_active` (`last_active_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='用户最近活跃摘要';

CREATE TABLE IF NOT EXISTS `campaign_execution` (
  `id` BIGINT NOT NULL AUTO_INCREMENT,
  `activity_id` BIGINT NOT NULL,
  `status` VARCHAR(24) CHARACTER SET ascii COLLATE ascii_bin NOT NULL COMMENT 'PENDING/RUNNING/COMPLETED/FAILED',
  `treatment_ratio_bps` INT NOT NULL DEFAULT 9000 COMMENT '实验组占比，万分比',
  `total_users` INT NOT NULL DEFAULT 0,
  `treatment_users` INT NOT NULL DEFAULT 0,
  `control_users` INT NOT NULL DEFAULT 0,
  `sent_users` INT NOT NULL DEFAULT 0,
  `failed_users` INT NOT NULL DEFAULT 0,
  `version` INT NOT NULL DEFAULT 1,
  `started_at` DATETIME(3) NULL,
  `completed_at` DATETIME(3) NULL,
  `last_error` VARCHAR(500) NULL,
  `created_at` DATETIME(3) NOT NULL,
  `updated_at` DATETIME(3) NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_campaign_execution_activity` (`activity_id`),
  KEY `idx_campaign_execution_status_updated` (`status`, `updated_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='活动执行实例';

CREATE TABLE IF NOT EXISTS `campaign_target_user` (
  `id` BIGINT NOT NULL AUTO_INCREMENT,
  `execution_id` BIGINT NOT NULL,
  `activity_id` BIGINT NOT NULL,
  `user_id` BIGINT NOT NULL,
  `experiment_group` VARCHAR(16) CHARACTER SET ascii COLLATE ascii_bin NOT NULL COMMENT 'TREATMENT/CONTROL',
  `delivery_channel` VARCHAR(24) CHARACTER SET ascii COLLATE ascii_bin NOT NULL COMMENT 'IN_APP/DEMO_PUSH/NONE',
  `points_snapshot` BIGINT NOT NULL,
  `last_active_at_snapshot` DATETIME(3) NULL,
  `data_source` VARCHAR(16) CHARACTER SET ascii COLLATE ascii_bin NOT NULL COMMENT 'REAL/FIXTURE',
  `assigned_at` DATETIME(3) NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_campaign_target_activity_user` (`activity_id`, `user_id`),
  KEY `idx_campaign_target_execution_group` (`execution_id`, `experiment_group`),
  KEY `idx_campaign_target_user_time` (`user_id`, `assigned_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='活动目标用户与实验分组快照';

CREATE TABLE IF NOT EXISTS `campaign_delivery_task` (
  `id` BIGINT NOT NULL AUTO_INCREMENT,
  `execution_id` BIGINT NOT NULL,
  `activity_id` BIGINT NOT NULL,
  `target_user_id` BIGINT NOT NULL,
  `user_id` BIGINT NOT NULL,
  `channel` VARCHAR(24) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  `status` VARCHAR(24) CHARACTER SET ascii COLLATE ascii_bin NOT NULL COMMENT 'PENDING/PROCESSING/SENT/RETRY_WAIT/DEAD',
  `attempt_count` INT NOT NULL DEFAULT 0,
  `max_attempts` INT NOT NULL DEFAULT 3,
  `next_attempt_at` DATETIME(3) NOT NULL,
  `claimed_at` DATETIME(3) NULL,
  `sent_at` DATETIME(3) NULL,
  `last_error` VARCHAR(500) NULL,
  `created_at` DATETIME(3) NOT NULL,
  `updated_at` DATETIME(3) NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_campaign_delivery_activity_user_channel` (`activity_id`, `user_id`, `channel`),
  KEY `idx_campaign_delivery_dispatch` (`status`, `next_attempt_at`, `id`),
  KEY `idx_campaign_delivery_execution` (`execution_id`, `status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='活动可靠投放任务';

CREATE TABLE IF NOT EXISTS `user_notification` (
  `id` BIGINT NOT NULL AUTO_INCREMENT,
  `delivery_task_id` BIGINT NOT NULL,
  `activity_id` BIGINT NOT NULL,
  `user_id` BIGINT NOT NULL,
  `title` VARCHAR(120) NOT NULL,
  `content` VARCHAR(1000) NOT NULL,
  `status` VARCHAR(16) CHARACTER SET ascii COLLATE ascii_bin NOT NULL COMMENT 'UNREAD/READ/CLICKED',
  `read_at` DATETIME(3) NULL,
  `clicked_at` DATETIME(3) NULL,
  `created_at` DATETIME(3) NOT NULL,
  `updated_at` DATETIME(3) NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_user_notification_delivery_task` (`delivery_task_id`),
  KEY `idx_user_notification_user_status_time` (`user_id`, `status`, `created_at`),
  KEY `idx_user_notification_activity_user` (`activity_id`, `user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='用户站内消息';

CREATE TABLE IF NOT EXISTS `campaign_event` (
  `id` BIGINT NOT NULL AUTO_INCREMENT,
  `event_key` VARCHAR(128) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  `activity_id` BIGINT NOT NULL,
  `user_id` BIGINT NOT NULL,
  `event_type` VARCHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL COMMENT 'DELIVERED/VIEW/CLICK/LOGIN/TASK_COMPLETE/EXCHANGE',
  `source` VARCHAR(16) CHARACTER SET ascii COLLATE ascii_bin NOT NULL COMMENT 'REAL/SIMULATED',
  `occurred_at` DATETIME(3) NOT NULL,
  `metadata_json` JSON NULL,
  `created_at` DATETIME(3) NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_campaign_event_key` (`event_key`),
  KEY `idx_campaign_event_activity_type_time` (`activity_id`, `event_type`, `occurred_at`),
  KEY `idx_campaign_event_user_time` (`user_id`, `occurred_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='活动行为事件';
