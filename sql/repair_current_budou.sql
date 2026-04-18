-- 修复脚本：用于修正当前 budu 库中影响秒杀链路压测的结构与数据问题。
USE `budou`;

SET @idx_user_award := (
  SELECT COUNT(*)
  FROM information_schema.statistics
  WHERE table_schema = DATABASE()
    AND table_name = 'user_award'
    AND index_name = 'idx_user_award_user_award_status'
);
SET @sql_user_award := IF(
  @idx_user_award = 0,
  'ALTER TABLE user_award ADD KEY idx_user_award_user_award_status (userId, awardId, status)',
  'SELECT ''skip idx_user_award_user_award_status'''
);
PREPARE stmt_user_award FROM @sql_user_award;
EXECUTE stmt_user_award;
DEALLOCATE PREPARE stmt_user_award;

SET @idx_user_task := (
  SELECT COUNT(*)
  FROM information_schema.statistics
  WHERE table_schema = DATABASE()
    AND table_name = 'user_task'
    AND index_name = 'uk_user_task_userId'
);
SET @sql_user_task := IF(
  @idx_user_task = 0,
  'ALTER TABLE user_task ADD UNIQUE KEY uk_user_task_userId (userId)',
  'SELECT ''skip uk_user_task_userId'''
);
PREPARE stmt_user_task FROM @sql_user_task;
EXECUTE stmt_user_task;
DEALLOCATE PREPARE stmt_user_task;

UPDATE `award_inventory_split`
SET `inventory` = 100
WHERE `awardId` = 6
  AND `inventory` <> 100;
