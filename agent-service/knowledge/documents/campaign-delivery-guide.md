---
knowledge_id: campaign-delivery-guide
title: 活动执行与用户触达说明
version: 1.0.0
status: active
audience: [operator]
topics: [campaign, execution, delivery, notification]
fact_scope: stable_rules_only
business_type: delivery_guide
authority_level: system_contract
effective_from: 2026-08-24
source_refs:
  - docs/agent-design/46_运营活动审核发布与效果回流.md
  - agent-service/app/operator/agent.py
---

# 活动执行与用户触达说明

## 适用问题

用于回答“活动发布后如何触达用户”“发布是否等于已经发送通知”“需要接入哪些触达渠道”等活动执行问题。

## 规则说明

- 活动草案、活动发布、活动执行和用户触达是不同阶段，不能混为一个动作。
- 活动发布表示通过审核的草案已经生成活动事实。活动可以处于待开始或进行中状态，但这不代表通知已经送达用户。
- 完整触达链路通常由活动执行器读取活动与目标客群，生成幂等的触达任务，再调用站内信、App Push、短信或邮件等渠道。
- 触达任务需要记录目标用户、渠道、发送状态和业务幂等键，并处理限流、失败重试、渠道回执和重复发送问题。
- 渠道回执只能证明渠道是否接收或送达；点击率、参与率和兑换转化率还需要通过后续行为数据计算。
- 用户询问“怎么触达”是在咨询方案时，应先说明上述流程，不能只回复助手没有执行权限。

## 实时信息边界

当前项目已经实现活动草案、人工审核、确定性发布和人工录入效果指标。发布只生成待执行或生效中的活动记录；活动执行器、目标用户明细任务、真实通知渠道和自动回执采集尚未实现。因此系统不能声称已经向用户发送通知。

## 来源

- 运营活动闭环设计定义了草案、审核、发布和效果回流的当前实现。
- 运营 Agent 提示词定义了模型与确定性业务服务之间的执行边界。
