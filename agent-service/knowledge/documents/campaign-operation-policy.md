---
knowledge_id: campaign-operation-policy
title: 运营活动草案制度
version: 1.0.0
status: active
audience: [operator]
topics: [campaign, planning, review, budget]
fact_scope: stable_rules_only
business_type: campaign_policy
authority_level: official_policy
effective_from: 2026-08-22
source_refs:
  - agent-service/app/skills/campaign_planning.py
  - agent-service/app/operator_tools.py
  - agent-service/skills/campaign-planning/SKILL.md
  - docs/agent-design/37_运营活动草案最小闭环.md
---

# 运营活动草案制度

## 适用问题

用于判断活动草案需要哪些输入、哪些数据不能由模型猜测，以及一份草案能否直接发布。制度编号为 `OPS-POLICY-CAMPAIGN-001`。

## 规则说明

- 活动草案必须包含活动目标、服务端支持的目标客群、奖品金额预算、积分发放上限和活动时间窗口。
- 奖品金额预算使用人民币分，约束企业承担的奖品成本；积分发放上限约束任务产生的积分。两者不能按固定比例换算。
- 用户群规模、任务规则、奖品库存、奖品单位成本和历史参与率必须来自只读事实快照，模型不得自行补全。
- 快照超过 24 小时、客群不一致或关键事实缺失时，不得继续生成看似完整的草案。
- 草案只能处于可编辑、不可发布、必须人工审核的状态。机器检查通过不等于活动获准发布。
- 当前奖品选择只校验可用性、库存、成本和时间窗口；奖品是否匹配活动目标仍由运营人员审核。

## 实时信息边界

当前客群规模、库存、奖品成本、任务状态和历史指标必须通过运营只读 Tool 获取。本文档只解释制度，不能替代规划快照，也不能作为活动发布指令。

## 来源

- 活动规划 Skill 定义快照、约束检查和草案状态。
- 运营 Tool 定义读取与草案权限边界。
- 活动草案设计文档解释金额、积分和人工审核口径。
