---
knowledge_id: campaign-exception-handbook
title: 运营活动草案异常处理手册
version: 1.0.0
status: active
audience: [operator]
topics: [campaign, exception, troubleshooting, risk]
fact_scope: stable_rules_only
business_type: incident_manual
authority_level: operations_manual
effective_from: 2026-08-22
source_refs:
  - agent-service/app/campaign_data.py
  - agent-service/app/operator_tools.py
  - agent-service/app/skills/campaign_planning.py
---

# 运营活动草案异常处理手册

## 适用问题

用于处理运营规划快照读取失败、关键数据缺失和约束冲突。手册编号为 `OPS-RUNBOOK-CAMPAIGN-001`。

## 规则说明

- `CAMPAIGN_SEGMENT_NOT_FOUND`：客群键不存在。核对服务端支持的固定客群标识，不要让模型临时拼接 SQL 或客群条件。
- `SEGMENT_SNAPSHOT_MISMATCH`：简报客群与快照客群不一致。重新获取目标客群快照后再规划。
- `STALE_PLANNING_SNAPSHOT`：快照超过 24 小时或时间异常。刷新快照，不沿用旧库存和旧指标。
- `EMPTY_SEGMENT`：目标客群规模为零。先检查客群条件和数据计算任务。
- `PARTICIPATION_RATE_MISSING`：缺少历史参与率。补充同类历史指标或由运营提供可追溯估算依据，不得让模型猜测。
- `AWARD_UNIT_COST_MISSING`：候选奖品缺少真实单位成本。由采购或运营数据补齐，不得用兑换积分换算金额。
- `NO_TASK_FITS_POINTS_CAP`：任务奖励无法放入人均积分发放上限。调整积分发放上限或任务组合。
- `NO_AWARD_FITS_AMOUNT_BUDGET`：金额预算不足以配置候选奖品。调整金额预算、候选奖品或计划数量。
- `NO_AWARD_AVAILABLE_FOR_WINDOW`：没有库存充足且覆盖完整活动时间的奖品。调整活动窗口或补充候选奖品。
- `AWARD_INVENTORY_COVERAGE_LOW`：奖品计划无法覆盖预计参与人数。这是警告，需核对获奖机制和库存策略。
- 只读数据源暂时不可用时可以刷新后重试；草案生成和发布不能绕过缺失数据或阻断风险。

## 实时信息边界

错误码解释是稳定知识，错误是否仍然存在、当前快照内容和修复后的结果必须重新调用运营 Tool 确认。手册不授权修改库存、规则或数据库。

## 来源

- 数据提供器定义只读快照异常。
- 运营 Tool 定义权限与结构化错误返回。
- 活动规划 Skill 定义缺数据、冲突和风险代码。
