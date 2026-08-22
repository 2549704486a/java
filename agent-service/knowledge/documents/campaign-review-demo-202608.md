---
knowledge_id: campaign-review-demo-202608
title: 高积分用户召回活动演示复盘
version: 1.0.0
status: active
audience: [operator]
topics: [campaign, review, participation, recall]
fact_scope: stable_rules_only
business_type: campaign_review
authority_level: historical_case
effective_from: 2026-08-22
source_refs:
  - agent-service/evals/campaign_cases.json
  - agent-service/evals/results/campaign_planning_baseline_20260822.json
  - docs/agent-design/39_运营活动草案评测基线.md
---

# 高积分用户召回活动演示复盘

## 适用问题

用于演示运营 Agent 如何引用历史案例估算参与人数、识别库存覆盖风险。案例编号为 `DEMO-CAMPAIGN-202608-001`。这是评测 Fixture，不是线上真实活动，不得包装成生产经营结论。

## 规则说明

- 演示客群为当前积分不少于 500 的用户，样例规模为 1000 人。
- 演示历史指标 `campaign_metric_history:101` 的参与率为 20%，样本量为 3000，因此草案估算参与人数为 200。
- 在奖品金额预算 16000 元、积分发放上限 50000 的样例约束下，确定性草案预计发放 36000 积分，计划奖品成本 16000 元。
- 演示草案只能证明算法满足给定约束，不能证明 20% 参与率适用于其他客群、渠道或时间窗口。
- 使用历史案例前必须核对活动目标、客群口径、样本时间和数据来源。缺少可比依据时应返回待补数据，而不是照搬演示值。

## 实时信息边界

本文中的人数、参与率、预算和成本均来自冻结评测数据，只服务于演示、回归和方法说明。真实活动必须读取当前只读快照和真实历史指标。

## 来源

- 运营活动 Fixture 提供冻结输入和预期结果。
- 冻结评测结果保存草案约束检查数据。
- 评测基线文档说明演示数据与真实业务数据的边界。
