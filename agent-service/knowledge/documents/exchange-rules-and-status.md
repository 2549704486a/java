---
knowledge_id: exchange-rules-and-status
title: 奖品兑换规则与状态
version: 1.1.0
status: active
audience: [end_user]
topics: [exchange, eligibility, status]
fact_scope: stable_rules_only
business_type: exchange_rule
authority_level: system_contract
effective_from: 2026-08-21
source_refs:
  - incentive/src/main/java/com/budou/incentive/service/AgentQueryService.java
  - incentive/src/main/java/com/budou/incentive/service/AgentExchangeCommandService.java
  - agent-service/app/services/controlled_exchange.py
---

# 奖品兑换规则与状态

## 适用问题

用于解释兑换需要满足哪些条件、为什么需要确认，以及“处理中”“成功”“失败”和“提交结果未知”分别意味着什么。

## 规则说明

- 兑换资格取决于用户、奖品、活动时间、库存、积分和既有兑换记录等条件，最终以系统的实时查询结果为准。
- Agent 发起兑换前必须先生成包含奖品和积分信息的确认摘要；只有用户在同一会话明确确认后，系统才会提交兑换。
- “处理中”只表示兑换请求已经受理并进入后台处理流程，不表示兑换成功。
- “已经兑换过”表示该奖品已经兑换成功，或已有不能重复提交的兑换记录。
- “暂时无法确认是否受理”表示系统目前无法判断请求是否已经提交成功。此时不要重复兑换，应先到订单页面核对。
- 最终兑换结果由旧事务消息链路异步处理，用户应在订单页面查看成功或失败状态。

## 实时信息边界

奖品价格、库存、活动起止时间、用户积分、兑换资格和订单状态都必须通过系统实时查询或订单页面获取。本文档不能用于判断某次兑换现在是否成功。

## 来源

- Java 查询服务定义兑换资格及原因码。
- Java 命令服务定义受理、幂等重放和提交结果未知的语义。
- Python 受控兑换 Skill 定义准备、确认、取消和一次性凭证边界。
