# Skill 运行时标准化

> 本章说明当前项目中的真实 Skill 是什么，以及它怎样进入模型上下文。最重要的边界是：`SKILL.md` 是给模型阅读的执行说明，Tool 是模型可调用入口，Service 是完成确定性业务计算的代码。三者不能互相冒充。

## 1. 为什么要纠偏

课程第十讲给出的定义是：

```text
Skill = Tool + 触发条件 + 执行流程 + 上下文知识
```

旧实现虽然会扫描和校验 `SKILL.md`，但正文只停留在 Python 对象中。模型直接调用业务 Tool，Tool 再调用当时命名为 `PointsPlanningSkill` 等 Python 类。因此旧链路实际上是：

```text
模型 -> 业务 Tool -> 确定性 Python 代码 -> Java 接口
```

这是一条有效的 Tool Calling 链路，却不能证明模型读过 Skill。现在已经把这两件事分开：

| 组件 | 当前职责 | 例子 |
| --- | --- | --- |
| `skills/*/SKILL.md` | 告诉模型何时使用、执行哪些步骤、怎样处理失败 | `skills/points-planning/SKILL.md` |
| `load_skill` | 命中任务后把对应正文作为 Tool 结果返回模型 | `app/skills/loader.py` |
| 业务 Tool | 给模型提供参数明确的调用入口 | `plan_points_for_award` |
| Service | 查询事实并执行可测试的业务计算或状态控制 | `app/services/points_planning.py` |

## 2. 当前真实运行流程

```text
Agent 启动
  -> SkillRegistry 扫描并校验 skills/*/SKILL.md
  -> System Prompt 只获得当前 Agent 可用的名称、描述和触发条件

用户提出“帮我规划兑换 6 号奖品所需积分”
  -> 模型根据目录判断命中 points-planning
  -> 模型调用 load_skill(skill_name="points-planning")
  -> load_skill 返回该 SKILL.md 的完整正文
  -> 正文以 ToolMessage 进入本轮 Agent 消息列表
  -> 模型阅读正文，调用 plan_points_for_award
  -> Tool 调用 PointsPlanningService
  -> Service 查询实时资格、积分和任务并完成确定性计算
  -> 模型把结构化结果解释给用户
```

这里的“加载”不是只在日志里写一行，也不是 Python 自己读到文件就结束。验收标准是：完整正文必须出现在 `load_skill` 的 Tool 返回值中，并进入下一次模型调用可见的消息上下文。

## 3. 为什么不在启动时加载所有正文

如果启动时把五份 Skill 全塞进 System Prompt，哪怕用户只问“我有多少积分”，模型也要携带积分规划、奖品推荐、长期记忆、受控兑换和活动规划的全部说明。这会增加上下文体积，也容易让不相关规则互相干扰。

当前采用渐进披露：

1. **启动阶段**：只披露名称、描述和触发条件，让模型知道“有哪些能力”。
2. **任务命中阶段**：调用 `load_skill`，只加载当前需要的一份正文。
3. **执行阶段**：模型按照正文调用业务 Tool；Tool 再进入确定性 Service。

例如，用户只查询当前积分时直接调用积分查询 Tool，不需要加载任何 Skill；用户要求“结合任务帮我规划怎样攒够积分”时，才加载 `points-planning`。

## 4. 文件契约

每个 Skill 位于：

```text
skills/<skill-name>/SKILL.md
```

YAML Front Matter 必须包含：

- `name`
- `description`
- `trigger`
- `version`

正文必须包含：

- `何时使用`
- `输入`
- `执行步骤`
- `错误与重试`
- `安全边界`
- `输出`

`SkillRegistry` 在启动时完成目录名、元数据、重复名称和正文章节校验。损坏的 Skill 会在提供服务前暴露，而不是等模型执行到一半再猜。

## 5. Skill 与 Service 的边界

积分规划可以最直观地说明两者为何都需要：

```text
points-planning/SKILL.md
  负责：告诉模型何时规划、先调用哪个组合 Tool、失败后停止追加查询

plan_points_for_award Tool
  负责：校验 award_id 等输入，向模型暴露稳定调用契约

PointsPlanningService
  负责：计算积分缺口、过滤任务并选择最小覆盖方案
```

把所有计算都交给模型，结果容易随表达变化；只保留 Service 而不让模型读取 `SKILL.md`，则只是普通 Tool Calling。当前结构同时保留模型可读流程和确定性业务内核。

## 6. Agent 隔离

两个 Agent 只能加载各自允许的 Skill：

| Agent | 可加载 Skill |
| --- | --- |
| 兑换助手 | `points-planning`、`award-recommendation`、`controlled-exchange`、`growth-memory` |
| 智能运营 Agent | `campaign-planning` |

例如，兑换助手尝试加载 `campaign-planning` 会返回 `SKILL_NOT_AVAILABLE`。这既减少无关上下文，也避免把运营能力暴露给普通用户 Agent。

## 7. 当前验证标准

关键测试不只检查文件能否被读取，还要覆盖以下事实：

1. 启动 Prompt 只有 Skill 目录，没有完整正文。
2. `load_skill` 返回真实正文，并拒绝未知或越界名称。
3. `load_skill` 的返回内容以 ToolMessage 进入 Agent 循环，下一次模型调用可见。
4. 后续业务 Tool 仍调用确定性 Service，关键计算没有转移给模型。
5. Tool 轨迹能够还原 `load_skill -> 业务 Tool` 的实际顺序。

完整的错误审计、代码正名和迁移映射见 `59_Skill事实审计与运行时纠偏.md`。
