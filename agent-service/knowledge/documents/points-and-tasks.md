---
knowledge_id: points-and-tasks
title: 积分与任务规则
version: 1.0.0
status: active
audience: [end_user]
topics: [points, tasks, rewards]
fact_scope: stable_rules_only
source_refs:
  - incentive/src/main/java/com/budou/incentive/service/AgentQueryService.java
  - agent-service/app/skills/points_plan.py
---

# 积分与任务规则

## 适用问题

用于解释积分如何获得、任务处于什么状态，以及 Agent 如何生成积分规划。它不提供某个用户当前有多少积分，也不承诺当前一定存在某项任务。

## 规则说明

- 用户通过完成有效任务并领取奖励获得积分，完成任务和领取积分是两个不同动作。
- `AVAILABLE` 表示任务可以参与；`COMPLETED_UNCLAIMED` 表示任务已经完成但积分尚未领取；`REWARDED` 表示奖励已经领取，不应再次推荐。
- Agent 可以根据目标奖品所需积分、用户当前积分和当前可用任务生成任务组合。
- 当所有可用任务的奖励仍不能覆盖积分缺口时，Agent 应明确说明完成这些任务后仍差多少积分，不能虚构额外任务。

## 实时信息边界

用户当前积分、当前有效任务、每项任务奖励和任务状态都可能变化，回答前必须调用 `get_user_points`、`list_available_tasks` 或 `plan_points_for_award`。本文档只能解释规则，不能替代 Tool 的实时结果。

## 来源

- Java 查询服务定义任务状态和可用任务过滤规则。
- Python 积分规划 Skill 使用 Tool 结果进行确定性缺口和任务组合计算。
