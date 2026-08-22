-- 本地演示数据：清理核心业务表中的历史压测数据，生成关系一致、可解释的数据。
-- 只清理积分激励系统的业务表，不处理 test_lock 等独立测试表。
USE `budou`;

SET NAMES utf8mb4;
START TRANSACTION;

-- Step 1: 按依赖关系从业务流水向配置表清理，避免违反外键约束。
DELETE FROM `inventory_log`;
DELETE FROM `add_currency_record`;
DELETE FROM `campaign_metric_history`;
DELETE FROM `agent_exchange_request`;
DELETE FROM `idempotent_table`;
DELETE FROM `user_award`;
DELETE FROM `finish_task_record`;
DELETE FROM `user_task`;
DELETE FROM `award_inventory_split`;
DELETE FROM `task_config`;
DELETE FROM `user_currency`;
DELETE FROM `award_config`;

-- Step 2: 创建不同价位、类型和库存规模的奖品，活动长期有效。
INSERT INTO `award_config`
(`awardId`, `coverUrl`, `name`, `awardType`, `inventory`, `price`, `unitCostCents`,
 `startTime`, `endTime`, `createTime`, `updateTime`, `initInventory`, `isOverSell`)
VALUES
(1, '/static/award/bluetooth-headset.png', '蓝牙耳机', 1, 119, 800, 12900,
 DATE_SUB(NOW(), INTERVAL 30 DAY), DATE_ADD(NOW(), INTERVAL 365 DAY),
 NOW(), NOW(), 120, 0),
(2, '/static/award/smart-band.png', '智能手环', 1, 60, 1500, 19900,
 DATE_SUB(NOW(), INTERVAL 30 DAY), DATE_ADD(NOW(), INTERVAL 365 DAY),
 NOW(), NOW(), 60, 0),
(3, '/static/award/video-membership.png', '视频会员月卡', 2, 500, 300, 1500,
 DATE_SUB(NOW(), INTERVAL 30 DAY), DATE_ADD(NOW(), INTERVAL 365 DAY),
 NOW(), NOW(), 500, 1),
(4, '/static/award/coffee-coupon.png', '精品咖啡券', 2, 300, 180, 2500,
 DATE_SUB(NOW(), INTERVAL 30 DAY), DATE_ADD(NOW(), INTERVAL 365 DAY),
 NOW(), NOW(), 300, 1),
(5, '/static/award/mechanical-keyboard.png', '机械键盘', 1, 24, 2500, 29900,
 DATE_SUB(NOW(), INTERVAL 30 DAY), DATE_ADD(NOW(), INTERVAL 365 DAY),
 NOW(), NOW(), 24, 0),
(6, '/static/award/smart-watch.png', '智能手表', 1, 19, 5000, 49900,
 DATE_SUB(NOW(), INTERVAL 30 DAY), DATE_ADD(NOW(), INTERVAL 365 DAY),
 NOW(), NOW(), 20, 0);

-- 普通实物奖品使用库存分片；每个奖品的分片库存之和等于 award_config.inventory。
INSERT INTO `award_inventory_split` (`splitId`, `awardId`, `inventory`) VALUES
(1, 1, 9), (2, 1, 10), (3, 1, 10), (4, 1, 10),
(5, 1, 10), (6, 1, 10), (7, 1, 10), (8, 1, 10),
(9, 1, 10), (10, 1, 10), (11, 1, 10), (12, 1, 10),
(1, 2, 6), (2, 2, 6), (3, 2, 6), (4, 2, 6), (5, 2, 6),
(6, 2, 6), (7, 2, 6), (8, 2, 6), (9, 2, 6), (10, 2, 6),
(1, 5, 4), (2, 5, 4), (3, 5, 4),
(4, 5, 4), (5, 5, 4), (6, 5, 4),
(1, 6, 1), (2, 6, 2), (3, 6, 2), (4, 6, 2), (5, 6, 2),
(6, 6, 2), (7, 6, 2), (8, 6, 2), (9, 6, 2), (10, 6, 2);

-- Step 3: 创建符合积分增长场景的任务，奖励从低频日常任务到高价值拉新任务递增。
INSERT INTO `task_config`
(`taskId`, `taskName`, `currency`, `startTime`, `endTime`, `type`, `description`)
VALUES
(1, '每日签到', 20, DATE_SUB(NOW(), INTERVAL 30 DAY), DATE_ADD(NOW(), INTERVAL 365 DAY), 1,
 '每日登录并完成签到'),
(2, '浏览精选商品', 30, DATE_SUB(NOW(), INTERVAL 30 DAY), DATE_ADD(NOW(), INTERVAL 365 DAY), 1,
 '浏览精选商品页面并停留指定时长'),
(3, '分享活动', 50, DATE_SUB(NOW(), INTERVAL 30 DAY), DATE_ADD(NOW(), INTERVAL 365 DAY), 2,
 '将积分活动分享给好友'),
(4, '完善个人资料', 100, DATE_SUB(NOW(), INTERVAL 30 DAY), DATE_ADD(NOW(), INTERVAL 365 DAY), 2,
 '补充头像、昵称和常用联系方式'),
(5, '完成用户调研', 80, DATE_SUB(NOW(), INTERVAL 30 DAY), DATE_ADD(NOW(), INTERVAL 365 DAY), 2,
 '填写产品体验问卷'),
(6, '邀请新用户', 200, DATE_SUB(NOW(), INTERVAL 30 DAY), DATE_ADD(NOW(), INTERVAL 365 DAY), 3,
 '邀请一名新用户注册并完成首次登录');

-- Step 4: 使用少量积分梯度用户覆盖不足、刚好满足和高积分等业务场景。
INSERT INTO `user_currency` (`userId`, `currency`, `createTime`, `updateTime`) VALUES
(1, 120, DATE_SUB(NOW(), INTERVAL 180 DAY), NOW()),
(2, 260, DATE_SUB(NOW(), INTERVAL 170 DAY), NOW()),
(3, 480, DATE_SUB(NOW(), INTERVAL 160 DAY), NOW()),
(4, 760, DATE_SUB(NOW(), INTERVAL 150 DAY), NOW()),
(5, 980, DATE_SUB(NOW(), INTERVAL 140 DAY), NOW()),
(6, 1250, DATE_SUB(NOW(), INTERVAL 130 DAY), NOW()),
(7, 1550, DATE_SUB(NOW(), INTERVAL 120 DAY), NOW()),
(8, 2300, DATE_SUB(NOW(), INTERVAL 110 DAY), NOW()),
(9, 3200, DATE_SUB(NOW(), INTERVAL 100 DAY), NOW()),
(10, 1680, DATE_SUB(NOW(), INTERVAL 90 DAY), NOW()),
(11, 5400, DATE_SUB(NOW(), INTERVAL 80 DAY), NOW()),
(12, 80, DATE_SUB(NOW(), INTERVAL 70 DAY), NOW()),
(13, 650, DATE_SUB(NOW(), INTERVAL 60 DAY), NOW()),
(14, 1900, DATE_SUB(NOW(), INTERVAL 50 DAY), NOW()),
(15, 2750, DATE_SUB(NOW(), INTERVAL 45 DAY), NOW()),
(16, 4200, DATE_SUB(NOW(), INTERVAL 40 DAY), NOW()),
(17, 350, DATE_SUB(NOW(), INTERVAL 35 DAY), NOW()),
(18, 1450, DATE_SUB(NOW(), INTERVAL 30 DAY), NOW()),
(19, 5100, DATE_SUB(NOW(), INTERVAL 25 DAY), NOW()),
(20, 880, DATE_SUB(NOW(), INTERVAL 20 DAY), NOW());

INSERT INTO `user_task` (`userId`, `completedTasks`)
SELECT userId, 0 FROM `user_currency`;

-- Step 5: 补充相互对应的任务、积分流水和兑换历史，形成可解释的用户故事。
INSERT INTO `finish_task_record` (`userId`, `taskId`, `finishTime`, `status`) VALUES
(3, 1, DATE_SUB(NOW(), INTERVAL 5 DAY), 1),
(5, 2, DATE_SUB(NOW(), INTERVAL 3 DAY), 0),
(8, 3, DATE_SUB(NOW(), INTERVAL 2 DAY), 0),
(10, 1, DATE_SUB(NOW(), INTERVAL 2 DAY), 1),
(10, 2, DATE_SUB(NOW(), INTERVAL 3 HOUR), 0),
(11, 4, DATE_SUB(NOW(), INTERVAL 10 DAY), 1),
(14, 5, DATE_SUB(NOW(), INTERVAL 1 DAY), 0),
(18, 3, DATE_SUB(NOW(), INTERVAL 6 HOUR), 0);

UPDATE `user_task` user_task
SET `completedTasks` = (
  SELECT COUNT(*)
  FROM `finish_task_record` record
  WHERE record.userId = user_task.userId
);

INSERT INTO `add_currency_record`
(`userId`, `currency`, `afterCurrency`, `description`, `requestId`, `createTime`)
VALUES
(3, 20, 480, '每日签到奖励', '3:1', DATE_SUB(NOW(), INTERVAL 5 DAY)),
(10, 20, 1680, '每日签到奖励', '10:1', DATE_SUB(NOW(), INTERVAL 2 DAY)),
(11, 100, 5400, '完善个人资料奖励', '11:4', DATE_SUB(NOW(), INTERVAL 10 DAY));

INSERT INTO `user_award`
(`id`, `userId`, `awardId`, `status`, `createTime`, `updateTime`) VALUES
(202608200001, 8, 1, 1, DATE_SUB(NOW(), INTERVAL 7 DAY), DATE_SUB(NOW(), INTERVAL 7 DAY)),
(202608200002, 11, 6, 1, DATE_SUB(NOW(), INTERVAL 4 DAY), DATE_SUB(NOW(), INTERVAL 4 DAY)),
(202608200003, 4, 4, -1, DATE_SUB(NOW(), INTERVAL 2 DAY), DATE_SUB(NOW(), INTERVAL 2 DAY));

INSERT INTO `idempotent_table` (`idempotent_key`, `create_time`) VALUES
('userId:8-awardId:1', DATE_SUB(NOW(), INTERVAL 7 DAY)),
('userId:11-awardId:6', DATE_SUB(NOW(), INTERVAL 4 DAY));

INSERT INTO `inventory_log` (`userId`, `awardId`, `inventory`, `splitId`, `creatTime`) VALUES
(8, 1, 9, 1, DATE_SUB(NOW(), INTERVAL 7 DAY)),
(11, 6, 1, 1, DATE_SUB(NOW(), INTERVAL 4 DAY));

-- 演示环境的历史活动指标。草案只读取已有记录，缺失时不会自行猜测参与率。
INSERT INTO `campaign_metric_history`
(`segment_key`, `metric_name`, `metric_value`, `sample_size`, `measured_at`, `source_ref`) VALUES
('ALL_USERS', 'participation_rate', 0.180000, 20, DATE_SUB(NOW(), INTERVAL 7 DAY),
 'demo_campaign_report:all_users:202608'),
('POINTS_AT_LEAST_500', 'participation_rate', 0.260000, 16, DATE_SUB(NOW(), INTERVAL 7 DAY),
 'demo_campaign_report:points_at_least_500:202608');

COMMIT;
