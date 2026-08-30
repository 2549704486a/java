# Skill 事实审计与运行时纠偏

> 本文只回答两件事：当前代码实际上做了什么，以及怎样修正为课程第十讲所描述的 Skill。此前将“确定性业务工作流”直接称为 Skill 的表述不再作为后续开发依据。

最后更新：`2026-08-27`

## 1. 课程中的基准定义

课程第十讲把 Skill 定义为一组面向具体场景的相关能力：

```text
Skill = Tool + 触发条件 + 执行流程 + 上下文知识
```

`SKILL.md` 负责告诉模型“何时使用、怎样执行、有哪些约束”，Tool 或脚本负责完成真实动作。多个 Skill 并存时采用渐进披露：启动时只提供名称、描述和触发条件，任务命中后才把对应正文交给模型。

## 2. 修正前的真实实现

| 原有组件 | 实际行为 | 审计结论 |
| --- | --- | --- |
| `SkillRegistry` | 扫描并校验 `SKILL.md`，读取正文 | 正文只保存在 Python 对象中，没有进入模型上下文 |
| `activate()` | 返回 Skill 定义并写日志 | 不会改变模型上下文，也不驱动业务执行 |
| `PointsPlanningSkill` 等类 | 查询业务接口、执行计算和状态控制 | 本质是 Service 或 Workflow，不是 Skill 加载器 |
| `plan_points_for_award` 等 Tool | 由模型直接调用，再调用上述 Python 类 | 这是 Tool 调用确定性业务服务 |
| `SKILL.md` 正文 | 描述流程、错误处理与边界 | 运行时没有让模型读取，修改正文不会改变模型行为 |

因此，修正前的实际调用链是：

```text
模型 -> Tool -> Python 业务服务 -> Java 接口
```

它已经具备真实 Tool Calling 和可测试的业务流程，但不具备“命中后加载 Skill 正文”的闭环。

## 3. 目标调用链

```text
Agent 启动
  -> 只向模型提供相关 Skill 的名称、描述和触发条件

用户提出具体任务
  -> 模型判断命中的 Skill
  -> 调用 load_skill(name)
  -> 运行时读取并返回对应 SKILL.md 正文
  -> 模型按照正文选择业务 Tool
  -> Tool 调用确定性 Service
  -> 模型根据 Tool 结果回答
```

Skill 与 Service 的边界如下：

| 层次 | 负责什么 | 不负责什么 |
| --- | --- | --- |
| Skill | 触发条件、步骤、Tool 使用方法、错误和安全边界 | 不直接访问数据库或伪造动态事实 |
| Tool | 模型可调用入口、参数校验、可信身份注入、结果结构化 | 不复制业务算法 |
| Service | 资格判断、任务组合、推荐排序、状态控制等确定性逻辑 | 不决定模型什么时候使用能力 |

## 4. 代码正名

| 修正前 | 修正后 |
| --- | --- |
| `PointsPlanningSkill` | `PointsPlanningService` |
| `SavedGoalPlanningSkill` | `SavedGoalPlanningService` |
| `AwardRecommendationSkill` | `AwardRecommendationService` |
| `ControlledExchangeSkill` | `ControlledExchangeService` |
| `GrowthMemorySkill` | `GrowthMemoryService` |
| `CampaignPlanningSkill` | `CampaignPlanningService` |

这些代码不会被删除，因为其中的确定性业务逻辑仍然有价值；修正的是名称、目录和调用关系。

## 5. 验收标准

1. 模型初始上下文只包含 Skill 目录，不包含所有正文。
2. `load_skill` 返回当前 Agent 被允许使用的真实 `SKILL.md` 正文。
3. 未知或越界的 Skill 名称不能被加载。
4. Skill 支撑的业务 Tool 继续调用确定性 Service，不把关键计算交给模型猜测。
5. 轨迹能够看到 `load_skill` 和后续业务 Tool 的实际执行顺序。
6. 设计文档、学习清单和面试材料不再把 Service 类称作 Skill。

## 6. 已落地的代码

| 位置 | 当前作用 |
| --- | --- |
| `app/skills/registry.py` | 启动时发现和校验 Skill，并生成不含正文的精简目录 |
| `app/skills/loader.py` | 提供 `load_skill` Tool，按当前 Agent 白名单返回真实正文 |
| `app/prompt.py` | 只把 Skill 目录放入 System Prompt，并要求命中后先加载 |
| `app/tools.py` | 注册兑换助手的加载 Tool 与业务 Tool |
| `app/operator/tools.py` | 只在活动规划能力可用时注册运营加载 Tool |
| `app/services/` | 保存积分规划、推荐、记忆、受控兑换和活动草案的确定性实现 |
| `skills/*/SKILL.md` | 保存模型真正阅读的触发条件、步骤、错误处理和安全边界 |

兑换助手和运营 Agent 使用不同白名单：普通用户不能加载活动规划 Skill，运营 Agent 也不会获得用户兑换相关 Skill。

## 7. 直接证据

关键测试不是只断言 `registry.load()` 能读到文件，而是让一个可调用 Tool 的假模型实际运行两轮：

```text
第一轮模型消息
  -> AIMessage 调用 load_skill(points-planning)

Agent 执行 Tool
  -> ToolMessage 返回 points-planning/SKILL.md 正文

第二轮模型收到
  -> SystemMessage
  -> HumanMessage
  -> AIMessage(tool_call)
  -> ToolMessage(包含 plan_points_for_award 执行说明)
```

对应测试为 `tests/test_skill_registry.py::test_loaded_body_becomes_tool_message_for_next_model_call`。它锁定的是“下一次模型调用确实看见正文”，可防止以后再次退化成只在 Python 内部读取文件。

此外使用真实模型配置和隔离 Fake Client 执行了一条“结合任务为 6 号奖品制定攒分计划”的代表场景，实际 Tool 顺序为：

```text
load_skill -> plan_points_for_award
```

顺序断言为真。该冒烟只验证模型是否遵循加载流程，不访问 Java，也不修改任何业务数据。

完成源码引用迁移并重建知识索引后，Python 最终回归共执行 `199` 条测试并全部通过，另有 `9` 条环境型测试按条件跳过。
