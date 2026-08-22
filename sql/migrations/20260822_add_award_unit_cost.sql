-- 为运营活动预算增加真实金额事实。price 仍表示兑换积分，不能当作人民币成本。
USE `budou`;

ALTER TABLE `award_config`
  ADD COLUMN `unitCostCents` int DEFAULT NULL
  COMMENT '奖品单位成本，单位分；与兑换积分无固定换算关系'
  AFTER `price`;

-- 迁移后应由运营或采购数据回填真实成本。成本为空时，活动草案会拒绝估算金额。
