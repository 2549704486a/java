---
knowledge_id: campaign-rule-change-20260822
title: 活动预算口径变更通知
version: 1.0.0
status: active
audience: [operator]
topics: [campaign, change, budget, points, cost]
fact_scope: stable_rules_only
business_type: rule_change_notice
authority_level: official_policy
effective_from: 2026-08-22
policy_key: campaign_budget_semantics
supersedes: [campaign-budget-policy-legacy]
source_refs:
  - agent-service/app/models.py
  - agent-service/app/operator/tools.py
  - agent-service/app/services/campaign_planning.py
  - sql/migrations/20260822_add_award_unit_cost.sql
  - docs/agent-design/37_运营活动草案最小闭环.md
---

# 活动预算口径变更通知

## 适用问题

用于解释 2026-08-22 起活动草案为何同时出现奖品金额预算和积分发放上限，以及旧的单一积分预算口径为何不再使用。通知编号为 `OPS-NOTICE-20260822-001`。

## 规则说明

- 自 2026-08-22 起，活动奖品预算统一使用 `budget_amount_cents`，单位为人民币分。
- 任务积分约束使用 `points_issuance_cap`，含义是本次活动最多计划发放的积分，不再称为金额预算。
- 奖品成本使用 `unit_cost_cents`，计划成本按单位成本乘以计划数量计算。
- 奖品兑换所需积分继续使用 `required_points`，只表示用户兑换门槛。
- 系统不得在奖品成本和兑换积分之间建立固定汇率，也不得在缺少单位成本时自动推算金额。
- 旧草案或旧文档若把积分发放量写成活动预算，应按本通知的新口径重新解释和生成。

## 实时信息边界

本通知定义字段语义，不提供当前预算、奖品成本或积分上限。具体金额和积分约束必须读取当前活动简报与规划快照。

## 来源

- Python 活动模型和 Tool 定义新字段契约。
- 奖品单位成本迁移脚本定义数据库字段。
- 活动草案设计文档记录新旧口径及其边界。
