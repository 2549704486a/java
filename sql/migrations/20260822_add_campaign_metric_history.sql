USE `budou`;

CREATE TABLE IF NOT EXISTS `campaign_metric_history` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `segment_key` varchar(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL COMMENT '服务端支持的固定客群标识',
  `metric_name` varchar(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL COMMENT '指标名称',
  `metric_value` decimal(10,6) NOT NULL COMMENT '指标值',
  `sample_size` int NOT NULL COMMENT '统计样本数',
  `measured_at` datetime(3) NOT NULL COMMENT '指标统计时间',
  `source_ref` varchar(255) NOT NULL COMMENT '指标来源说明',
  PRIMARY KEY (`id`),
  KEY `idx_campaign_metric_segment_name_time` (`segment_key`, `metric_name`, `measured_at`),
  CONSTRAINT `chk_campaign_metric_value` CHECK ((`metric_value` >= 0) AND (`metric_value` <= 1)),
  CONSTRAINT `chk_campaign_metric_sample_size` CHECK (`sample_size` > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='运营活动历史指标';

-- 迁移脚本不伪造历史参与率。请由真实活动报表写入指标；没有记录时草案返回待补数据。
