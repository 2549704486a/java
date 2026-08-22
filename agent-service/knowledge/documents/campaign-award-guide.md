---
knowledge_id: campaign-award-guide
title: 运营奖品字段与选品说明
version: 1.0.0
status: active
audience: [operator]
topics: [campaign, award, cost, inventory]
fact_scope: stable_rules_only
business_type: award_guide
authority_level: system_contract
effective_from: 2026-08-22
source_refs:
  - agent-service/app/models.py
  - agent-service/app/skills/campaign_planning.py
  - incentive/src/main/java/com/budou/incentive/dao/model/AwardConfig.java
  - incentive/src/main/java/com/budou/incentive/service/AgentOperatorQueryService.java
---

# 运营奖品字段与选品说明

## 适用问题

用于解释活动规划中的兑换积分、奖品单位成本、库存和计划数量分别表示什么，以及缺少奖品成本时为什么不能生成金额方案。说明编号为 `OPS-GUIDE-AWARD-001`。

## 规则说明

- `required_points` 是用户兑换一个奖品需要的积分，只用于判断兑换门槛。
- `unit_cost_cents` 是企业提供一个奖品的单位成本，单位为人民币分，用于核算奖品金额预算。
- `inventory` 是生成快照时读取到的可用库存；普通奖品读取库存分片合计，允许超发的奖品读取配置库存。
- `planned_quantity` 是草案建议配置的奖品数量，不能超过快照库存，也不能使计划成本超过金额预算。
- `planned_cost_cents` 等于计划数量乘以单位成本。
- 兑换积分与单位成本是两个独立口径。缺少单位成本时不得用兑换积分反推金额。
- 当前算法优先按单位成本规划覆盖人数，这只是确定性初稿，不代表最终选品结论。

## 实时信息边界

具体奖品名称、兑换积分、单位成本、库存和活动有效期会变化，必须从当前运营规划快照读取。本文档不提供任何奖品的当前数值。

## 来源

- Python 数据模型定义奖品快照和草案奖品字段。
- Java 运营查询服务提供奖品配置、单位成本与库存来源。
- 活动规划 Skill 定义预算和库存约束。
