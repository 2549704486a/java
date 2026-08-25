# 运营 Agent 运行时 Harness

> 本文既是本次 Harness 改造的需求 Spec，也是 AI 辅助开发过程记录。开发遵循“先澄清需求，再拆分 Spec，小步实现、评审、定向测试，最后人工验收”的流程，不以模型声称完成作为交付依据。

## 1. 为什么需要 Harness

运营人员提出：

> 计算最近 7 天，积分不少于 500 的用户中，阅读活动消息后完成兑换的比例。

旧链路实际只调用了：

```text
list_campaign_activities
get_campaign_planning_snapshot
get_campaign_funnel
```

漏斗只给出了“阅读人数 8”和“兑换人数 3”两个独立聚合值，没有证明兑换者一定属于已阅读用户，也没有证明阅读发生在兑换之前。模型却自行生成了 `3 / 8 = 37.5%`。这说明现有系统能约束 Tool 参数格式，却不能约束“任务是否受支持”和“结论是否具有足够证据”。

Harness 在本项目中的定位是：包围模型执行过程的确定性运行时。模型负责理解自然语言和组织表达，代码负责能力准入、参数来源、Tool 范围、证据要求和失败降级。

## 2. 需求评审

### 2.1 要解决的问题

1. 粗粒度的“知识、规划、执行”意图无法区分标准报表与自定义分析。
2. 模型可以调用相近 Tool 后自行组合数字，形成未被数据源证明的结论。
3. Tool 是否必须调用、内部参数应该由谁提供，目前主要依赖 Prompt。
4. Tool 轨迹能观察调用过程，但不能判断当前任务是否已取得最低充分证据。

### 2.2 本轮边界

本轮实现：

- 结构化 `TaskSpec`；
- 能力注册表与准入判断；
- 参数来源声明；
- 按能力收敛 Tool；
- 执行后最低证据校验；
- 不支持任务的确定性降级；
- Harness 决策日志与关键测试。

本轮不实现：

- 任意 SQL 或自然语言转 SQL；
- 自定义指标计算引擎；
- 通用数学证明器；
- 第二个评审模型；
- 多 Agent 编排；
- 全量回归与大规模在线评测。

## 3. 数据模型

### 3.1 TaskSpec 示例

```json
{
  "intent": "PLAN_REQUEST",
  "capability": "CUSTOM_ANALYTICS",
  "confidence": 0.96,
  "requested_action": "计算带时间窗、客群条件和事件顺序的转化比例",
  "reason": "请求要求按用户交集及事件先后进行自定义统计"
}
```

`TaskSpec` 只描述任务，不直接授予 Tool 或写操作权限。

### 3.2 CapabilityContract 示例

```json
{
  "capability": "CAMPAIGN_STANDARD_EFFECT",
  "supported": true,
  "allowed_tools": [
    "list_campaign_activities",
    "get_campaign_funnel"
  ],
  "required_evidence_tools": [
    "list_campaign_activities",
    "get_campaign_funnel"
  ],
  "parameter_sources": {
    "operator_id": "TRUSTED_CONTEXT",
    "activity_id": "SYSTEM_LOOKUP"
  }
}
```

### 3.3 参数来源

| 来源 | 含义 | 示例 |
| --- | --- | --- |
| `USER_INPUT` | 只有用户能决定，缺失时才追问 | 活动目标、预算、起止时间 |
| `TRUSTED_CONTEXT` | 来自认证上下文，禁止让模型或用户伪造 | 运营人员 ID |
| `SYSTEM_LOOKUP` | 系统能够通过 Tool 自动解析 | 最近活动的活动 ID |
| `TOOL_RESULT` | 必须由实时 Tool 返回 | 漏斗人数、Lift、库存 |

## 4. 执行流程

```text
用户输入
  -> 意图路由生成 TaskSpec
  -> Harness 查找 CapabilityContract
  -> 不支持：在调用业务 Agent 前确定性拒绝估算
  -> 支持：按契约提供最小 Tool 集
  -> Agent 调用 Tool 并生成回答
  -> Harness 校验必需 Tool 是否成功执行
  -> 证据不足：覆盖模型回答，返回确定性降级说明
  -> 证据充分：返回回答
```

## 5. 可独立验证的任务

| 任务 | 实现行为 | 不允许改变 | 验收方式 |
| --- | --- | --- | --- |
| H1 | 扩展路由输出为包含能力的 `TaskSpec` | 意图枚举现有语义 | 结构化路由与 fallback 单测 |
| H2 | 建立能力契约和参数来源 | 不新增业务服务层 | 契约单测 |
| H3 | 在 Agent 前执行准入，在 Agent 后校验证据 | 不把业务数据写入普通日志 | Runtime 单测 |
| H4 | 按能力缩小 Tool 集 | 不扩大任何写权限 | Tool 选择单测 |
| H5 | 增加反例 Fixture | 不运行全量模型回归 | 关键定向测试 |
| H6 | 评审并记录结果 | 不用“测试通过”替代人工审查 | 本文第 7、8 节 |

## 6. 验收标准

1. 自定义时间窗、客群过滤、事件顺序或用户交集统计被识别为 `CUSTOM_ANALYTICS`。
2. `CUSTOM_ANALYTICS` 在调用业务 Agent 前终止，不产生未经支持的比例。
3. “查看活动历史”至少成功调用 `list_campaign_activities`。
4. “查看活动效果”至少成功调用 `list_campaign_activities` 和 `get_campaign_funnel`。
5. 模型未调用必需 Tool 或 Tool 执行失败时，最终响应不得保留模型的业务结论。
6. `activity_id` 被声明为 `SYSTEM_LOOKUP`，不能默认要求用户提供内部 ID。
7. 原有知识咨询、方案规划、草案生成和只读效果查询的 Tool 范围不扩大。
8. Harness 日志包含 TaskSpec、准入结果和证据校验摘要，但不复制完整业务数据。

## 7. AI 辅助开发过程记录

### 7.1 上下文与约束

- 事实来源：当前源码、现有测试、真实失败对话与 Tool 轨迹。
- 架构约束：Harness 是运行时约束，不新增 Capability/Adapter 业务层，不引入多 Agent。
- 测试约束：每个增量只跑关联单测；模块完成后再做一次运营 Agent 定向回归。
- 交付约束：代码、测试、路线图和任务日记一并提交，提交信息使用中文。

### 7.2 迭代记录

| 轮次 | 实现 | 评审发现 | 验证 | 处理 |
| --- | --- | --- | --- | --- |
| 1 | 增加 `TaskSpec`、能力枚举、能力契约和执行前准入 | 若模型仍把自定义统计误判为普通规划，契约会被绕过 | 运营 Agent 单测 `11/11` | 增加独立于模型结果的保守任务守卫 |
| 2 | 增加任务守卫、必需 Tool 校验和请求内 Tool 结果证据 | `activity_id=SYSTEM_LOOKUP` 只有声明，没有证明漏斗 ID 确实来自活动列表 | 运营 Agent 单测 `13/13` | 校验漏斗参数必须属于本轮活动列表返回的 ID |
| 3 | 将完整 Tool 结果限制在请求内，补相邻模块回归和真实 HTTP 验收 | 完整 Tool 结果若写入普通轨迹会扩大日志和敏感数据暴露面 | 定向回归 `27/27`；真实请求 `2/2` | 日志只保留结果码和校验摘要，完整结果随请求结束释放 |

## 8. 最终评审与验证

### 8.1 Code Review 结果

| 严重度 | 位置 | 问题与后果 | 处理结果 |
| --- | --- | --- | --- |
| 高 | `operator/intent.py` | 只根据模型输出选择契约，模型误分类时仍可能越过能力边界 | 增加确定性任务守卫；模型把原失败误判为普通规划时也会被覆盖为 `CUSTOM_ANALYTICS` |
| 高 | `operator/harness.py` | 只检查 Tool 名称，无法证明漏斗参数来自活动发现结果 | 增加请求内结果证据，校验漏斗活动 ID 属于本轮活动列表 |
| 中 | `trace.py` | 为来源校验保存完整 Tool 结果可能污染普通日志 | 完整结果只进入请求内 `ToolResultEvidence`；`as_dicts()` 继续只输出摘要，并由测试固定该边界 |
| 低 | 自定义统计守卫 | 规则过宽会把“如何计算”这类方法咨询误当成执行统计 | 显式保留“如何计算、怎么计算”为知识咨询，并增加反例测试 |

没有发现 Harness 扩大写权限、改变 Java 业务状态或把完整业务结果写入普通日志的问题。

### 8.2 自动验证

执行命令：

```powershell
.\.venv\Scripts\python.exe -m unittest `
  tests.test_operator_agent `
  tests.test_trace `
  tests.test_operator_api `
  tests.test_campaign_workflow -v
```

结果：`27/27` 通过。覆盖任务分类、模型误分类守卫、能力准入、最小 Tool 集、内部 ID 来源、必需证据、轨迹隐私、运营 API 和活动工作流。

按照“减少回归频率”的约定，本轮没有运行与改动无关的用户记忆、RAG、前端和 Java 全量测试。

### 8.3 真实 HTTP 验收

#### 自定义统计

请求：

```text
计算最近 7 天，积分不少于 500 的用户中，阅读活动消息后完成兑换的比例。
```

结果：

- `capability=CUSTOM_ANALYTICS`；
- `code=CAPABILITY_UNSUPPORTED`；
- 两次验收总耗时约 `2.2s`，主要来自结构化任务分类；
- 没有构建业务 Agent，没有调用活动列表、快照或漏斗 Tool；
- 回答明确说明缺少用户交集、时间窗和事件顺序的确定性统计能力，没有再次返回 `3 / 8`。

#### 标准活动效果

请求：

```text
查看活动历史以及收益
```

结果：

```text
CAMPAIGN_STANDARD_EFFECT
  -> list_campaign_activities       成功，约 16.38ms
  -> get_campaign_funnel(2)         活动尚无执行数据，约 7.27ms
  -> get_campaign_funnel(1)         成功，约 14.63ms
  -> EVIDENCE_SUFFICIENT
```

活动 `1`、`2` 均来自本轮活动列表，来源校验通过；整个请求约 `9349ms`，主要耗时仍在两次模型调用而不是 Tool。

### 8.4 尚未覆盖的风险

1. 当前 Harness 证明“能力受支持、必需 Tool 已成功、关键参数来源合法”，不能逐句理解最终自然语言中的所有数字关系。
2. 标准漏斗中的比率由后端确定性计算，模型负责转述；若未来允许模型组合多个指标，应增加确定性指标计算 Tool 或独立答案评审器。
3. 任务守卫只覆盖当前已知的高风险统计表达；新的业务分析维度需要先进入能力契约和冻结用例，不能只补 Prompt。
4. 自定义统计目前选择诚实降级，而不是伪装成已实现；后续若产品确有需求，应新增用户事件明细查询和确定性指标服务。

- 问题位置和证据；
- 问题类型与严重程度；
- 可能后果；
- 修改结果；
- 单元测试与端到端验证；
- 尚未覆盖的风险。
