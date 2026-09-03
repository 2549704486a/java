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

## 5. 实施记录

### 2026-09-03 数据契约

- 增加两张观测摘要表及迁移脚本。
- 增加请求与 Tool 的 Pydantic 数据模型，校验时间、Token 成对缺失和 Tool 顺序。
- 增加独立开关、队列、留存和数据库连接配置。
- 已在本地 MySQL 8.0 执行迁移：重复请求主键未产生第二行，删除请求后关联 Tool 行为 `0`，实际列清单不含身份、对话和 Tool 正文字段。
- 当前尚未接入运行时采集、查询 API 和前端页面。
