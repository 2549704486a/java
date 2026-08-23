USE `budou`;

CREATE TABLE IF NOT EXISTS `campaign_plan_draft` (
  `id` BIGINT NOT NULL AUTO_INCREMENT,
  `draft_key` VARCHAR(64) NOT NULL,
  `version` INT NOT NULL DEFAULT 1,
  `operator_id` VARCHAR(64) NOT NULL,
  `objective` VARCHAR(200) NOT NULL,
  `target_segment_key` VARCHAR(64) NOT NULL,
  `target_segment` VARCHAR(200) NOT NULL,
  `budget_amount_cents` BIGINT NOT NULL,
  `points_issuance_cap` BIGINT NOT NULL,
  `start_at` DATETIME(3) NOT NULL,
  `end_at` DATETIME(3) NOT NULL,
  `plan_json` LONGTEXT NOT NULL,
  `status` VARCHAR(32) NOT NULL,
  `reviewer_id` VARCHAR(64) NULL,
  `review_comment` VARCHAR(500) NULL,
  `reviewed_at` DATETIME(3) NULL,
  `published_by` VARCHAR(64) NULL,
  `published_at` DATETIME(3) NULL,
  `created_at` DATETIME(3) NOT NULL,
  `updated_at` DATETIME(3) NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_campaign_plan_draft_key` (`draft_key`),
  KEY `idx_campaign_plan_draft_status_updated` (`status`, `updated_at`),
  KEY `idx_campaign_plan_draft_operator` (`operator_id`, `created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `campaign_plan_audit` (
  `id` BIGINT NOT NULL AUTO_INCREMENT,
  `draft_id` BIGINT NOT NULL,
  `action` VARCHAR(32) NOT NULL,
  `from_status` VARCHAR(32) NULL,
  `to_status` VARCHAR(32) NOT NULL,
  `operator_id` VARCHAR(64) NOT NULL,
  `comment` VARCHAR(500) NULL,
  `created_at` DATETIME(3) NOT NULL,
  PRIMARY KEY (`id`),
  KEY `idx_campaign_plan_audit_draft` (`draft_id`, `created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `campaign_activity` (
  `id` BIGINT NOT NULL AUTO_INCREMENT,
  `draft_id` BIGINT NOT NULL,
  `objective` VARCHAR(200) NOT NULL,
  `target_segment_key` VARCHAR(64) NOT NULL,
  `budget_amount_cents` BIGINT NOT NULL,
  `points_issuance_cap` BIGINT NOT NULL,
  `start_at` DATETIME(3) NOT NULL,
  `end_at` DATETIME(3) NOT NULL,
  `plan_json` LONGTEXT NOT NULL,
  `status` VARCHAR(32) NOT NULL,
  `published_by` VARCHAR(64) NOT NULL,
  `published_at` DATETIME(3) NOT NULL,
  `created_at` DATETIME(3) NOT NULL,
  `updated_at` DATETIME(3) NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_campaign_activity_draft` (`draft_id`),
  KEY `idx_campaign_activity_status_time` (`status`, `start_at`, `end_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS `campaign_effect_metric` (
  `id` BIGINT NOT NULL AUTO_INCREMENT,
  `activity_id` BIGINT NOT NULL,
  `metric_name` VARCHAR(64) NOT NULL,
  `metric_value` DECIMAL(18,6) NOT NULL,
  `sample_size` INT NOT NULL,
  `measured_at` DATETIME(3) NOT NULL,
  `source_ref` VARCHAR(255) NOT NULL,
  `recorded_by` VARCHAR(64) NOT NULL,
  `created_at` DATETIME(3) NOT NULL,
  PRIMARY KEY (`id`),
  KEY `idx_campaign_effect_activity_time` (`activity_id`, `measured_at`),
  KEY `idx_campaign_effect_name_time` (`metric_name`, `measured_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
