---
knowledge_id: agent-service-guide
title: 积分兑换顾问使用说明
version: 1.1.0
status: active
audience: [end_user]
topics: [agent, guidance, safety]
fact_scope: stable_rules_only
business_type: service_guide
authority_level: operations_manual
effective_from: 2026-08-21
source_refs:
  - agent-service/app/prompt.py
  - agent-service/app/tools.py
  - docs/agent-context/07_Agent接入边界.md
---

# 积分兑换顾问使用说明

## 适用问题

用于说明积分兑换顾问可以帮助用户做什么、为什么不能跳过确认直接兑换，以及遇到异常时应该如何处理。

## 规则说明

- Agent 可以查询当前积分、有效任务、奖品信息和兑换资格，并生成积分规划或奖品推荐。
- 用户明确想兑换奖品时，Agent 可以先准备兑换摘要，但不能跳过用户确认直接提交。
- Agent 不能按用户要求修改积分、库存、任务状态或消息状态，也不能执行任意数据库和缓存命令。
- Agent 的推荐和解释不改变业务事实；资格、库存和最终结果仍由业务系统决定。
- 普通订单列表和兑换结果由页面承载，Agent 不把“请求已受理”描述为“兑换成功”。

## 实时信息边界

当问题包含“我的积分”“现在能否兑换”“还有多少库存”“活动是否结束”等词义时，必须调用对应 Tool。没有成功取得实时结果时，应明确说明暂时无法查询，不能用本文档中的规则推测答案。

## 来源

- System Prompt 定义 Agent 职责、回答方式和安全边界。
- Tool 注册表定义 Agent 当前可以调用的业务能力。
- Agent 接入边界文档定义只读、低风险写和高风险写操作的治理要求。
