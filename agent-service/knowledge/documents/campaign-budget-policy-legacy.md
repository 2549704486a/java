---
knowledge_id: campaign-budget-policy-legacy
title: 活动积分预算旧口径
version: 1.0.0
status: active
audience: [operator]
topics: [campaign, budget, points, legacy]
fact_scope: stable_rules_only
business_type: campaign_policy
authority_level: official_policy
effective_from: 2026-08-01
policy_key: campaign_budget_semantics
source_refs:
  - docs/agent-design/37_运营活动草案最小闭环.md
  - agent-service/app/services/campaign_planning.py
---

# 活动积分预算旧口径

## 适用问题

用于解释历史活动草案中的单一积分预算字段。制度编号为 `OPS-POLICY-BUDGET-LEGACY-001`。

## 规则说明

- 旧版活动草案使用积分数表示活动预算，没有单独记录奖品采购金额。
- 旧版草案可能把任务积分发放量和奖品兑换积分放在同一预算描述中。
- 该口径仅用于解释历史草案，不应直接套用到采用金额预算的新草案。

## 实时信息边界

本文档不提供当前预算，也不能替代当前活动简报。若存在更新的预算口径通知，应以新通知为准。

## 来源

- 活动草案设计文档记录了预算模型演进。
- 活动规划 Skill 的当前实现用于对照旧口径与新字段契约。
