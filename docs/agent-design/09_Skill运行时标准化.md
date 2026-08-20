# Skill 运行时标准化

> 这一阶段解决的问题是：以前 `SKILL.md` 只是给人看的说明书，Agent 实际只认识 Python Tool。现在声明文件成为运行时事实来源，但确定性业务计算仍由代码负责，避免把积分计算和异常分支交给模型自由发挥。

## 1. 为什么需要改造

原实现已经具备完整的积分规划代码，但存在两套彼此独立的信息：

| 载体 | 原有职责 | 原有问题 |
| --- | --- | --- |
| `skills/points-planning/SKILL.md` | 描述触发条件、流程和安全边界 | 运行时不读取，修改后不会影响 Agent |
| `app/skills/points_plan.py` | 查询业务数据并确定性计算积分方案 | 无法证明自己对应哪一版 Skill 声明 |
| `app/tools.py` | 将组合能力暴露给模型 | Tool 描述由代码硬编码，可能与声明漂移 |

课程第十节的核心定义是：`Skill = Tool + 触发条件 + 执行流程 + 上下文知识`。课程中的天气案例由 `SKILL.md` 描述“何时查询天气、需要组合哪些工具、如何给出出行建议”，由 `weather_api.py` 执行真实查询。本项目采用同样分层：声明文件负责能力契约，Python 代码负责可靠执行。

## 2. 当前运行时流程

```text
Agent 启动
  -> SkillRegistry 扫描 skills/*/SKILL.md
  -> 解析 YAML Front Matter
  -> 校验必要元数据和正文章节
  -> 将 description + trigger 作为 Tool 描述
  -> 将 name + version + SHA-256 写入 Tool 扩展元数据

用户询问积分规划
  -> 模型根据精简元信息选择 plan_points_for_award
  -> Tool 激活 points-planning Skill 定义
  -> 日志记录 Skill 名称、版本和哈希
  -> PointsPlanningSkill 执行确定性业务流程
  -> 结构化 PointsPlan 返回模型
```

初始上下文只包含触发所需的精简元信息，不把完整 `SKILL.md` 塞入 System Prompt。完整说明由运行时加载和校验，代码执行型 Skill 不需要模型重新解释步骤，因此不会增加每次请求的 Prompt 体积。

## 3. 声明契约

每个 Skill 必须位于与 `name` 同名的目录，并包含：

```text
skills/<skill-name>/SKILL.md
```

YAML Front Matter 必填：

- `name`
- `description`
- `trigger`
- `version`

正文必填章节：

- `何时使用`
- `输入`
- `执行步骤`
- `错误与重试`
- `安全边界`
- `输出`

缺少元数据、目录名不一致、名称重复或正文缺少必要章节时，Agent 启动失败。这样可以在请求到来前发现损坏的 Skill，而不是让模型在运行中猜测。

## 4. 渐进披露的具体边界

当前实现属于**代码执行型 Skill**：

- 模型初始只看到精简触发信息。
- Tool 被调用时激活完整 Skill 定义。
- 执行步骤由已经过测试的 Python 代码落实。
- `SKILL.md` 的完整正文不直接注入模型上下文。

这与“Prompt 执行型 Skill”不同。后者需要在触发后把完整说明注入模型，让模型按照步骤编排多个 Tool；适用于开放式研究或文档处理。本积分规划流程分支明确、计算可验证，使用确定性代码更可靠，也更节省 Token。

## 5. 可追踪性与评测

运行时记录：

```text
skill_activated name=points-planning version=1.0.0 sha256=...
skill_complete name=points-planning version=1.0.0 status=... elapsed_ms=...
```

评测结果元数据增加当前 Skill 的名称、版本和哈希。以后比较两次评测时，可以判断差异是否来自 Skill 定义变化，而不是只看 Prompt 和模型名称。

新增测试验证：

1. 能发现并激活 `points-planning`。
2. Tool 描述和扩展元数据来自 `SKILL.md`。
3. Tool 调用时确实执行运行时激活。
4. 缺少必要章节的 Skill 会被拒绝。

## 6. 当前完成度与后续边界

本阶段已经完成文件型声明、运行时注册、契约校验、精简元信息暴露、激活日志和版本追踪。它没有把所有正文交给模型，也没有为了形式增加一次 `load_skill` Tool 调用。

以后增加开放式 Skill 时，可以在同一个注册表上扩展“触发后注入完整说明”；在只有一个确定性积分规划 Skill 的当前阶段，不需要提前引入复杂的动态中间件。

## 7. 回归验证

- 离线单元测试：`13/13` 通过。
- 首轮模型回归：`13/15`，暴露一个评分同义短语遗漏和一个重复查询奖品列表的问题，原始结果保留在 `skill_runtime_fixture_20260820.json`。
- 针对性复验：E03、E06 均通过，结果保留在 `skill_runtime_targeted_20260820.json`。
- 最终完整回归：`15/15`，工具选择、参数、后端路径、回答内容和安全检查均为 `100%`，结果保留在 `skill_runtime_fixture_final_20260820.json`。

这里没有通过重复运行碰结果：先保留失败轨迹，再分别修正规则评分同义表达和 Skill 触发契约，最后执行全量回归。
