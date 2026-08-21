---
knowledge_id: exchange-rules-and-status
title: 奖品兑换规则与状态
version: 1.0.0
status: active
audience: [end_user]
topics: [exchange, eligibility, status]
fact_scope: stable_rules_only
source_refs:
  - incentive/src/main/java/com/budou/incentive/service/AgentQueryService.java
  - incentive/src/main/java/com/budou/incentive/service/AgentExchangeCommandService.java
  - agent-service/app/skills/controlled_exchange.py
---

# 奖品兑换规则与状态

## 适用问题

用于解释兑换需要满足哪些条件、为什么需要确认，以及“处理中”“成功”“失败”和“提交结果未知”分别意味着什么。

## 规则说明

- 兑换资格取决于用户、奖品、活动时间、库存、积分和既有兑换记录等条件，最终判断以资格查询 Tool 返回的原因码为准。
- Agent 发起兑换前必须先生成包含奖品和积分信息的确认摘要；只有用户在同一会话明确确认后，系统才会提交兑换。
- `EXCHANGE_PROCESSING` 只表示请求已经进入异步处理流程，不表示兑换成功。
- `ALREADY_REDEEMED` 表示该奖品已经兑换成功，或已有不能重复提交的兑换记录。
- `SUBMISSION_UNKNOWN` 表示系统无法确定请求是否已经受理。此时不能自动重试，应先到订单页面核对。
- 最终兑换结果由旧事务消息链路异步处理，用户应在订单页面查看成功或失败状态。

## 实时信息边界

奖品价格、库存、活动起止时间、用户积分、兑换资格和订单状态都必须通过 `get_award_detail`、`check_exchange_eligibility` 等 Tool 或订单页面获取。本文档不能用于判断某次兑换现在是否成功。

## 来源

- Java 查询服务定义兑换资格及原因码。
- Java 命令服务定义受理、幂等重放和提交结果未知的语义。
- Python 受控兑换 Skill 定义准备、确认、取消和一次性凭证边界。
