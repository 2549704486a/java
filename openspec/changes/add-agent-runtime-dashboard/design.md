## Context

参见 [proposal.md](./proposal.md) 的问题与范围。当前两类 Agent 都在 HTTP 请求边界记录请求 ID和端到端耗时，并通过 `capture_tool_trace` 收集 Tool 摘要；用户 Agent 的上下文中间件还会记录模型用量。但是这些信息只写日志，运营界面无法按时间窗口查询。离线评测 JSON 的“通过率”属于测试结果，不能作为线上运行事实源。

本次设计受以下约束：

- 不修改 Java 业务规则或旧事务消息兑换链路。
- 不记录对话正文、Tool 参数和业务返回正文，也不为统计活跃用户而保存调用者身份。
- 观测链路失败时，用户和运营人员仍应拿到原 Agent 响应。
- 复用现有 FastAPI 生命周期、PyMySQL 依赖、请求 ID、Tool 轨迹和运营鉴权，不搭建通用可观测平台。

## Goals / Non-Goals

**Goals:**

- 形成 `请求边界 -> 采集器 -> 持久化 -> 只读 API -> 运营界面` 的最小闭环。
- 让每个指标都有稳定分子、分母、时间窗口和缺失值语义。
- 新代码按“观测模型、存储、查询”职责收拢，不在 Agent、Tool 和前端重复计算口径。
- 通过专用权限与最小字段集控制运行数据暴露范围。

**Non-Goals:**

- 不建设日志搜索、告警中心、链路追踪平台或任意指标配置器。
- 不计算回答正确率、RAG 忠实度、业务收益或用户级留存。
- 不为未来多 Agent、MCP 或外部监控系统预留额外适配层。

## Decisions

### 1. MySQL 观测表是看板唯一事实源

新增两张追加式摘要表：

| 表 | 作用 | 关键字段 |
| --- | --- | --- |
| `agent_request_observation` | 一次 Agent 请求的终态摘要 | `request_id`、`agent_type`、`started_at`、`completed_at`、`status`、`elapsed_ms`、`model_call_count`、`input_tokens`、`output_tokens`、`tool_call_count`、`error_type` |
| `agent_tool_observation` | 请求内每次 Tool 调用的摘要 | `request_id`、`sequence`、`tool_name`、`transport`、`completed`、可空的 `business_success`、`result_code`、`elapsed_ms`、`error_type` |

`request_id` 是请求表主键，`request_id + sequence` 是 Tool 表唯一键。一次请求及其 Tool 轨迹在同一事务中幂等写入；Tool 表通过外键随请求记录一起清理。时间统一以 UTC 写入，API 返回带时区时间，浏览器按本地时区显示。

一条请求记录示例：

```json
{
  "requestId": "req-20260903-00017",
  "agentType": "OPERATOR",
  "startedAt": "2026-09-03T02:15:41.120Z",
  "completedAt": "2026-09-03T02:15:43.006Z",
  "status": "COMPLETED",
  "elapsedMs": 1886,
  "modelCallCount": 2,
  "inputTokens": 1240,
  "outputTokens": 186,
  "toolCallCount": 1,
  "errorType": null
}
```

对应的 Tool 记录示例：

```json
{
  "requestId": "req-20260903-00017",
  "sequence": 1,
  "toolName": "load_skill",
  "transport": null,
  "completed": true,
  "businessSuccess": null,
  "resultCode": null,
  "elapsedMs": 74,
  "errorType": null
}
```

选择 MySQL 是因为本项目已经使用同一数据库保存 Agent 长期事实，且看板需要时间范围、分组、分页和请求下钻。结构化日志继续用于排障，但不作为页面查询源；离线评测 JSON 继续用于评测报告，不进入这些表。

备选方案及结论：

- **保持现状，只查看日志**：改动最少，但不能稳定聚合、分页和授权给运营人员，无法完成看板闭环。
- **运行时解析日志**：无需新增表，但日志格式变化、轮转和多进程会造成漏数与重复，拒绝采用。
- **接入通用指标/链路平台**：适合更大规模服务，但会引入额外部署和查询系统，且不擅长当前所需的请求级业务下钻，第一版不采用。

### 2. 使用请求级观测上下文复用现有轨迹

新增一个仅在单次请求内存活的观测上下文。用户或运营请求通过认证后创建上下文，运行时沿用现有请求 ID；`run_agent` 与 `run_operator_agent` 在退出已有 `capture_tool_trace` 时，把轨迹快照交给当前上下文。无 Tool 的确定性回答仍会产生请求记录，但 `tool_call_count=0`。

模型用量通过本次 `ainvoke` 携带的调用回调累计，每次模型完成时读取供应商返回的用量元数据。这样不会从完整会话历史重复累计旧消息，也可以同时覆盖用户 Agent 与运营 Agent：

- 没有发生模型调用时，调用数和 Token 合法地记录为 `0`。
- 所有模型调用均提供用量时，记录累计值。
- 任一模型调用缺少可靠用量时，本次请求的 Token 字段为 `NULL`，页面显示未知，避免低估成本。

请求正常返回时终态为 `COMPLETED`；运行时异常导致接口无法给出 Agent 响应时为 `FAILED`。业务拒绝、库存不足、找不到知识等结果由 Tool 轨迹表达，不改变请求终态定义。

备选方案是修改所有 `answer()` 和 `run_agent()` 返回类型，让业务返回值携带观测数据。它虽然显式，但会把横切观测信息扩散到多个稳定接口和大量测试中；本次采用请求级上下文，保持业务方法签名不变。

### 3. 通过有界内存队列隔离观测写入

请求结束时只把不可变快照放入有界 `asyncio.Queue`，后台写入器在 FastAPI 生命周期内消费，并在线程中执行现有同步 MySQL 驱动。队列满、数据库不可用或单次写入失败时丢弃该条观测并记录请求 ID和错误类别，不阻塞或改写 Agent 响应；服务优雅关闭时在固定时限内尝试排空队列。

选择有界队列而不是请求内直接写库，是为了避免数据库故障给每次对话叠加连接超时。它的代价是进程崩溃时可能丢失少量尚未落库的观测数据；第一版接受这一点，因为这些数据不是订单、积分或活动事实。

不引入新的消息队列。业务 RocketMQ 链路只负责兑换事务消息，不应被复用成遥测通道。

### 4. 查询口径由 Agent 服务确定性计算

新增只读查询服务，统一计算完成率、平均值、P95、Token 覆盖率和 Tool 指标。SQL 负责按时间过滤和取出必要聚合数据，Python 负责按规范完成缺失值与最近秩 P95 计算；前端只负责展示，不重新定义公式。

汇总响应示例：

```json
{
  "window": "7d",
  "started_at": "2026-08-27T02:20:00Z",
  "ended_at": "2026-09-03T02:20:00Z",
  "requests": {
    "total": 120,
    "completed": 114,
    "failed": 6,
    "completion": {"numerator": 114, "denominator": 120, "value": 0.95},
    "latency": {"average_ms": 1724.0, "p95_ms": 3410}
  },
  "model_usage": {
    "model_call_count": 135,
    "covered_requests": 103,
    "coverage": {"numerator": 103, "denominator": 120, "value": 0.8583},
    "input_tokens": 80420,
    "output_tokens": 12580
  },
  "tools": {
    "total_calls": 86,
    "completed_calls": 83,
    "business_result_known_calls": 80,
    "business_successful_calls": 76,
    "execution_completion": {"numerator": 83, "denominator": 86, "value": 0.9651},
    "business_success": {"numerator": 76, "denominator": 80, "value": 0.95},
    "latency": {"average_ms": 68.2, "p95_ms": 145}
  }
}
```

当分母为零时，比率和 P95 返回 `null`，而不是 `0`。没有统一业务状态的已完成 Tool 不进入业务成功率的分子或分母。趋势在 `24h` 使用小时桶，在 `7d` 和 `30d` 使用日桶；响应同时返回区间起止时间，前端不猜测统计边界。

### 5. 三个只读接口共用专用权限

新增接口：

- `GET /v1/operator/agent-observability/summary?window=24h|7d|30d`
- `GET /v1/operator/agent-observability/requests?window=...&agent_type=...&status=...&page=...&page_size=...`
- `GET /v1/operator/agent-observability/requests/{request_id}`

三个接口先执行现有运营 Bearer 令牌认证，再要求 `agent:observe`。不存在的请求与无权访问使用不同的内部处理顺序：先鉴权、后查询，因此无权限调用者无法根据响应判断某个请求 ID是否存在。读取行为继续写入现有 HTTP 访问日志，形成最小审计证据。

`campaign:read` 与 `agent:observe` 是两项独立权限。拥有活动读取权限不会自动获得 Agent 运行数据；本地默认配置显式列出 `agent:observe`，部署环境仍以 `OPERATOR_PERMISSIONS` 的实际配置为准。

接口只返回观测 DTO，不返回数据库行的额外字段。最大窗口为 30 天，`page_size` 默认 20、上限 100。

### 6. 在现有运营工作台增加独立视图

不引入新的前端路由库。在 `/operator` 的现有工作台中增加“活动运营 / Agent 数据”视图切换；仅当 `/v1/operator/me` 返回 `agent:observe` 时显示 Agent 数据入口。

Agent 数据视图包含：

1. 时间窗口与手动刷新。
2. 请求总数、运行完成率、平均耗时、P95 耗时和 Token 覆盖情况。
3. 请求量与失败量趋势。
4. 按 Tool 名称拆分的调用数、执行完成率、业务成功率与 P95 耗时。
5. 最近请求列表和不含正文的轨迹详情抽屉。

加载、空数据、权限不足和接口失败均在该视图内部处理，不影响运营 Agent 对话和活动工作流。页面固定展示“运行完成不代表回答正确或业务成功”的口径说明。第一版不自动轮询，避免运营页面长期打开时制造无意义查询；用户需要时手动刷新。

### 7. 留存、初始化与回滚

新增独立迁移脚本，并同步更新全新环境的初始化脚本。观测功能使用独立开关和数据库连接配置；部署顺序是先执行迁移，再启用采集和查询。启动时仅检查表是否可读写，不由应用临时创建表。

后台写入器至多每天触发一次超过留存期数据的清理；删除请求记录时级联删除 Tool 记录。默认留存 30 天，可通过配置缩短，但接口最大查询范围仍为 30 天。

回滚时先关闭观测开关，再回滚应用和前端；新增表可以保留，不影响既有业务。确认不再需要历史观测后再通过独立数据库变更删除，代码回滚不自动删表。

## Risks / Trade-offs

- [进程崩溃会丢失队列中少量记录] -> 页面明确是运行观测而非审计账本；优雅关闭时限时排空，并通过丢弃告警发现持续性问题。
- [Token 元数据因模型供应商而缺失] -> 使用 `NULL` 和覆盖请求数表达完整性，不估算、不补零。
- [观测表增长影响查询] -> 限制 30 天窗口和分页上限，为时间、Agent 类型、状态及 Tool 请求关联建立索引，并定期清理。
- [指标名称造成错误业务解读] -> API 字段与 UI 文案固定使用“运行完成率”“Tool 执行完成率”“Tool 业务成功率”，同时展示分子、分母和口径说明。
- [单进程内存队列不适合大规模部署] -> 当前单体 Agent 服务规模可接受；只有出现可测量的丢数或吞吐瓶颈后，才评估外部遥测管道。
- [现有结构化日志中的 Tool 参数仍可能包含业务标识] -> 本次观测表不复制这些参数；日志脱敏属于独立问题，不借看板需求扩大范围。

## Migration Plan

1. 执行新增 MySQL 迁移并验证两张空表及索引。
2. 部署 Agent 服务代码，保持观测开关关闭，验证原用户与运营对话不受影响。
3. 开启观测采集，执行一条用户请求和一条运营请求，核对请求记录、Tool 顺序及 Token 缺失语义。
4. 部署前端并给目标运营身份增加 `agent:observe`，验证汇总、筛选和下钻。
5. 观察写入告警和接口耗时后完成验收；如异常，关闭开关并按上述回滚边界处理。
