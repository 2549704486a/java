# Agent 运行数据看板

## 1. 用户问题

当前用户 Agent 和运营 Agent 已有请求日志与 Tool 轨迹，但运营人员只能逐条翻日志，无法在界面中连续查看请求量、运行完成率、耗时和 Tool 调用分布。离线评测 JSON 又是测试数据，不能伪装成线上运行结果。

本模块建立一条独立的运行观测链路，不改变 Agent 的业务决策、Tool 契约、活动流程和兑换链路。

## 2. 第一版边界

第一版展示：

- 用户 Agent 与运营 Agent 的请求数、运行终态和端到端耗时。
- 模型调用次数与可获得的 Token 用量。
- Tool 调用顺序、执行完成情况、业务结果和耗时。
- 按固定时间窗口汇总的数据，以及按请求 ID下钻的最小轨迹。

第一版不保存：

- 用户提问和模型回答。
- Tool 参数和返回正文。
- 用户 ID、运营人员 ID、会话 ID和访问令牌。
- 离线评测成绩、活动收益或模拟数据。

## 3. 数据模型实例

### 3.1 AgentRequestObservation

```json
{
  "request_id": "req-20260903-00017",
  "agent_type": "OPERATOR",
  "started_at": "2026-09-03T02:15:41.120Z",
  "completed_at": "2026-09-03T02:15:43.006Z",
  "status": "COMPLETED",
  "elapsed_ms": 1886,
  "model_call_count": 2,
  "input_tokens": 1240,
  "output_tokens": 186,
  "error_type": null
}
```

`COMPLETED` 只说明 Agent 正常给出了响应，不说明回答正确，更不说明兑换或活动执行成功。

### 3.2 AgentToolObservation

```json
{
  "request_id": "req-20260903-00017",
  "sequence": 1,
  "tool_name": "get_campaign_funnel",
  "transport": "REST",
  "completed": true,
  "business_success": false,
  "result_code": "CAMPAIGN_NOT_FOUND",
  "elapsed_ms": 42,
  "error_type": null
}
```

这个例子表示 Tool 调用本身完整结束，但业务没有成功找到活动。它会计入 Tool 执行完成率，不会计入 Tool 业务成功率。

对于 `load_skill` 这类没有统一业务成功字段的 Tool，`business_success` 保存为 `null`。这类调用会计入执行完成率，但不会进入业务成功率的分子或分母。

## 4. 当前结构

```text
Agent HTTP 请求
    -> 请求级观测上下文
        -> 模型用量摘要
        -> 现有 ToolExecutionTrace
    -> agent_request_observation
    -> agent_tool_observation
    -> 运营只读 API
    -> /operator Agent 数据视图
```

MySQL 观测表是看板的运行事实源；结构化日志仍用于排障；离线评测文件仍用于测试报告。三者不混用。

## 5. 指标口径

| 指标 | 公式 | 特殊情况 |
| --- | --- | --- |
| 运行完成率 | `COMPLETED 请求数 / 请求总数` | 没有请求时为未知，不显示 `0%` |
| Tool 执行完成率 | `completed=true / Tool 调用总数` | Tool 抛出异常时不进入分子 |
| Tool 业务成功率 | `business_success=true / completed=true 且业务结果已知` | 纯文本等无业务状态 Tool 不进入分子或分母 |
| P95 耗时 | 升序排列后取 `ceil(数量 × 0.95)` 对应值 | 没有样本时为未知 |
| Token 覆盖率 | Token 完整可得请求数 / 请求总数 | 任一次模型调用缺失用量时，该请求 Token 为未知 |

汇总服务同时返回比率的分子、分母和值，前端只负责展示，不重新计算公式。`24h` 使用 24 个小时桶，`7d` 与 `30d` 分别使用 7 个和 30 个日桶。

## 6. 实施记录

### 2026-09-03 数据契约

- 增加两张观测摘要表及迁移脚本。
- 增加请求与 Tool 的 Pydantic 数据模型，校验时间、Token 成对缺失和 Tool 顺序。
- 增加独立开关、队列、留存和数据库连接配置。
- 已在本地 MySQL 8.0 执行迁移：重复请求主键未产生第二行，删除请求后关联 Tool 行为 `0`，实际列清单不含身份、对话和 Tool 正文字段。
- 已实现 MySQL 幂等保存、轨迹替换、过期清理、时间范围扫描、分页和请求详情查询。
- 已实现确定性汇总服务，并用 20 条固定请求验证 `19 / 20 = 95%`、P95 为第 19 个样本、未知 Token 不进入总量，以及 Tool 执行完成率与业务成功率分开计算。
- 已用本地 MySQL 验证同一请求重放后仅保留最新一条 Tool 轨迹，过期测试记录可以连同 Tool 记录一起清理。
- 根据现有 `ToolExecutionTrace` 的真实三态字段修正规划：`business_success` 允许未知，避免把没有业务状态的 Tool 错算为失败。
- 已实现请求级观测上下文：累计本次请求的模型调用、Token 和 Tool 摘要，只保留错误类型，不保存错误正文。
- 已实现进程内有界后台写入队列：请求线程只做非阻塞入队，队列满或数据库异常只记录告警，不修改 Agent 的业务响应。
- 当前尚未把观测上下文绑定到用户与运营请求，也尚未提供运营查询 API 和前端页面。
