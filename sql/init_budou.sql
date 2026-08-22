-- 初始化脚本：用于云上部署与压测演练，覆盖秒杀主链路和任务积分链路。
-- 说明：本脚本会重建核心业务表，请仅在全新环境或允许重置数据的环境中执行。

CREATE DATABASE IF NOT EXISTS `budou`
  DEFAULT CHARACTER SET utf8mb4
  DEFAULT COLLATE utf8mb4_0900_ai_ci;

USE `budou`;

SET NAMES utf8mb4;
SET FOREIGN_KEY_CHECKS = 0;

DROP TABLE IF EXISTS `finish_task_record`;
DROP TABLE IF EXISTS `user_task`;
DROP TABLE IF EXISTS `award_inventory_split`;
DROP TABLE IF EXISTS `add_currency_record`;
DROP TABLE IF EXISTS `inventory_log`;
DROP TABLE IF EXISTS `agent_long_term_memory`;
DROP TABLE IF EXISTS `agent_exchange_request`;
DROP TABLE IF EXISTS `idempotent_table`;
DROP TABLE IF EXISTS `user_award`;
DROP TABLE IF EXISTS `task_config`;
DROP TABLE IF EXISTS `user_currency`;
DROP TABLE IF EXISTS `award_config`;

CREATE TABLE `award_config` (
  `awardId` bigint NOT NULL COMMENT 'id',
  `coverUrl` varchar(200) NOT NULL COMMENT '封面',
  `name` varchar(50) NOT NULL COMMENT '名称',
  `awardType` tinyint NOT NULL COMMENT '1实物奖品 2虚拟奖品',
  `inventory` bigint NOT NULL COMMENT '奖品库存',
  `price` int NOT NULL COMMENT '兑换奖品消耗积分',
  `startTime` timestamp NULL DEFAULT NULL,
  `endTime` timestamp NULL DEFAULT NULL,
  `createTime` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updateTime` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  `initInventory` bigint NOT NULL DEFAULT '0' COMMENT '初始库存',
  `isOverSell` int NOT NULL DEFAULT '0' COMMENT '是否可超卖',
  PRIMARY KEY (`awardId`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='奖品表';

CREATE TABLE `user_currency` (
  `id` int NOT NULL AUTO_INCREMENT,
  `userId` bigint NOT NULL COMMENT '用户id',
  `currency` bigint NOT NULL COMMENT '用户总积分',
  `createTime` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updateTime` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_userId` (`userId`),
  CONSTRAINT `chk_currency_non_negative` CHECK ((`currency` >= 0))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='用户积分表';

CREATE TABLE `user_task` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `userId` bigint NOT NULL COMMENT '用户id',
  `completedTasks` int NOT NULL DEFAULT '0',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_user_task_userId` (`userId`),
  CONSTRAINT `user_task_ibfk_1` FOREIGN KEY (`userId`) REFERENCES `user_currency` (`userId`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE `task_config` (
  `taskId` bigint NOT NULL AUTO_INCREMENT COMMENT '任务id',
  `taskName` varchar(255) DEFAULT NULL COMMENT '任务名称',
  `currency` int DEFAULT NULL COMMENT '奖励积分',
  `startTime` timestamp NULL DEFAULT NULL,
  `endTime` timestamp NULL DEFAULT NULL,
  `type` int DEFAULT NULL,
  `description` varchar(255) DEFAULT NULL,
  PRIMARY KEY (`taskId`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE `finish_task_record` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `userId` bigint NOT NULL COMMENT '用户id',
  `taskId` bigint NOT NULL COMMENT '任务id',
  `finishTime` timestamp NULL DEFAULT NULL,
  `status` int NOT NULL DEFAULT '0',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_userId_taskId` (`userId`, `taskId`),
  KEY `taskId` (`taskId`),
  CONSTRAINT `finish_task_record_ibfk_1` FOREIGN KEY (`userId`) REFERENCES `user_currency` (`userId`),
  CONSTRAINT `finish_task_record_ibfk_2` FOREIGN KEY (`taskId`) REFERENCES `task_config` (`taskId`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE `user_award` (
  `id` bigint NOT NULL,
  `userId` bigint NOT NULL COMMENT '用户id',
  `awardId` bigint NOT NULL COMMENT '奖品ID',
  `status` tinyint NOT NULL COMMENT '奖品状态',
  `createTime` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updateTime` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`),
  KEY `idx_user_award_user_award_status` (`userId`, `awardId`, `status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='用户获奖表';

CREATE TABLE `idempotent_table` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `idempotent_key` varchar(64) NOT NULL,
  `create_time` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `idempotent_unique_key` (`idempotent_key`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='幂等性控制表';

CREATE TABLE `agent_exchange_request` (
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
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='Agent exchange request idempotency table';

CREATE TABLE `agent_long_term_memory` (
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

CREATE TABLE `award_inventory_split` (
  `splitId` bigint NOT NULL,
  `awardId` bigint NOT NULL COMMENT '奖品ID',
  `inventory` int NOT NULL COMMENT '库存',
  PRIMARY KEY (`splitId`, `awardId`),
  KEY `awardId` (`awardId`),
  CONSTRAINT `award_inventory_split_ibfk_1` FOREIGN KEY (`awardId`) REFERENCES `award_config` (`awardId`),
  CONSTRAINT `chk_inventory_non_negative` CHECK ((`inventory` >= 0))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE `add_currency_record` (
  `id` bigint NOT NULL AUTO_INCREMENT COMMENT 'id',
  `userId` bigint NOT NULL COMMENT 'userId',
  `currency` bigint NOT NULL COMMENT '积分',
  `afterCurrency` int DEFAULT NULL,
  `description` varchar(50) NOT NULL COMMENT '描述',
  `requestId` char(40) NOT NULL COMMENT '请求ID',
  `createTime` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `requestId` (`requestId`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='积分增加流水等表';

CREATE TABLE `inventory_log` (
  `userId` bigint DEFAULT NULL,
  `awardId` bigint DEFAULT NULL,
  `inventory` int DEFAULT NULL,
  `splitId` bigint DEFAULT NULL,
  `creatTime` timestamp NULL DEFAULT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

INSERT INTO `award_config` (`awardId`, `coverUrl`, `name`, `awardType`, `inventory`, `price`, `startTime`, `endTime`, `createTime`, `updateTime`, `initInventory`, `isOverSell`) VALUES
(5, '/static/award/hard-disk.png', '硬盘', 1, 1000, 100, '2024-10-06 12:29:19', '2027-07-03 21:37:45', NOW(), NOW(), 1000, 1),
(6, '/static/award/watch.png', '手表', 1, 1000, 200, '2024-10-10 22:19:53', '2027-07-29 14:15:01', NOW(), NOW(), 1000, 0);

INSERT INTO `award_inventory_split` (`splitId`, `awardId`, `inventory`) VALUES
(1, 6, 100),
(2, 6, 100),
(3, 6, 100),
(4, 6, 100),
(5, 6, 100),
(6, 6, 100),
(7, 6, 100),
(8, 6, 100),
(9, 6, 100),
(10, 6, 100);

INSERT INTO `task_config` (`taskId`, `taskName`, `currency`, `startTime`, `endTime`, `type`, `description`) VALUES
(1, '分享链接', 10, '2024-10-16 16:57:26', '2027-07-13 16:57:26', 1, '完成分享任务后领取积分');

SET SESSION cte_max_recursion_depth = 10000;

INSERT INTO `user_currency` (`userId`, `currency`, `createTime`, `updateTime`)
WITH RECURSIVE seq AS (
  SELECT 1 AS n
  UNION ALL
  SELECT n + 1 FROM seq WHERE n < 10000
)
SELECT n, 1000000, NOW(), NOW() FROM seq;

INSERT INTO `user_task` (`userId`, `completedTasks`)
WITH RECURSIVE seq AS (
  SELECT 1 AS n
  UNION ALL
  SELECT n + 1 FROM seq WHERE n < 10000
)
SELECT n, 0 FROM seq;

SET FOREIGN_KEY_CHECKS = 1;
