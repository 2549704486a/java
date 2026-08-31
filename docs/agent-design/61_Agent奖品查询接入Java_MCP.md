# Agent 奖品查询接入 Java MCP

> 本文记录第二阶段结果：Java MCP 最小样本不再只有协议测试客户端，用户兑换助手可以在显式实验模式下，把模型直接调用的 `get_award_detail` 切换为 Java MCP Tool。默认模式仍是 REST。

## 1. 这次解决什么问题

第一阶段已经证明 Java 服务能够同时提供 REST 和 Streamable HTTP MCP，但没有证明 LangChain Agent 能真实发现并执行 MCP Tool。

本次只验证一条最小闭环：

```text
用户提问
  -> 模型选择 get_award_detail
  -> Python 官方 LangChain MCP Adapter
  -> Java /mcp
  -> get_award_detail
  -> AgentQueryService
  -> 结构化业务 Envelope
  -> 模型组织回答
```

选择奖品详情，是因为它只有一个正整数 `award_id`，不需要用户身份，也不会修改积分、库存、订单或活动状态。

## 2. 两种运行模式

### 2.1 默认 REST 模式

```text
模型
  -> Python 本地 get_award_detail Tool
  -> BusinessApiClient
  -> Java REST Controller
  -> AgentQueryService
```

`.env` 保持：

```dotenv
AWARD_DETAIL_TRANSPORT=rest
```

Java MCP 没有启动也不影响 Agent 就绪。

### 2.2 MCP 实验模式

```text
Agent 启动
  -> 连接 Java /mcp
  -> 发现并校验 get_award_detail
  -> 用远程 Tool 替换模型可见的同名本地 Tool

模型调用
  -> MCP get_award_detail
  -> Java AgentQueryService
  -> 模型回答
```

需要同时开启 Java MCP 和 Agent 实验配置：

```powershell
$env:AGENT_MCP_ENABLED = "true"
```

```dotenv
AWARD_DETAIL_TRANSPORT=mcp
AWARD_DETAIL_MCP_URL=http://127.0.0.1:8088/mcp
AWARD_DETAIL_MCP_INITIALIZATION_TIMEOUT_SECONDS=5
AWARD_DETAIL_MCP_CALL_TIMEOUT_SECONDS=5
```

Agent 会在 HTTP 服务 ready 之前完成 Tool 发现和契约校验。连接失败、Tool 缺失或 Schema 漂移会直接导致启动失败，不会偷偷回退 REST。这样一次成功回答才能证明 MCP 确实参与了调用。

## 3. 哪些调用没有改成 MCP

切换点只在用户 Agent 的 Tool 组装阶段。以下确定性逻辑仍调用 `BusinessApiClient` 并走 REST：

- 积分规划；
- 奖品推荐；
- 长期目标规划；
- 受控兑换；
- 用户积分、资格、订单和通知等身份绑定查询；
- 运营 Agent 的全部能力；
- 所有写操作。

因此不能把本次结果描述为“Java 后端全部改成 MCP”或“所有 Agent Tool 都来自 MCP”。当前准确说法是：**只有用户兑换助手中模型直接可见的奖品详情 Tool，能够在显式实验模式下走 MCP。**

## 4. 关键实现

### 4.1 启动时发现并校验

`app/mcp_award_tool.py` 使用官方 `MultiServerMCPClient` 连接 Java Streamable HTTP Server，只允许绑定名为 `get_award_detail` 的 Tool。

期望的输入模型是：

```json
{
  "type": "object",
  "properties": {
    "award_id": {
      "type": "integer",
      "minimum": 1,
      "maximum": 9223372036854775807
    }
  },
  "required": ["award_id"],
  "additionalProperties": false
}
```

初始化错误会区分：

| 类别 | 含义 |
| --- | --- |
| `MCP_DISCOVERY_TIMEOUT` | 规定时间内没有完成 Tool 发现 |
| `MCP_UNAVAILABLE` | MCP Server 无法连接或协议调用失败 |
| `MCP_TOOL_MISSING` | Server 没有目标 Tool |
| `MCP_TOOL_DUPLICATED` | 同名目标 Tool 不止一个 |
| `MCP_CONTRACT_DRIFT` | 参数 Schema 与约定不一致 |

Server 将来新增其他 Tool 时，它们不会自动进入用户 Agent；当前允许清单仍只有一个奖品查询 Tool。

### 4.2 只替换模型入口

`build_tools()` 接受一个可选的 `award_detail_tool`。MCP 模式传入远程 Tool，REST 模式继续使用原本的本地 Tool，并且两者位于相同位置、名称相同。

切换没有放进 `BusinessApiClient.get_award_detail()`。否则积分规划、推荐和受控兑换等内部 Service 也会被一起改走 MCP，实验边界就无法判断。

### 4.3 为什么用户 Agent 改为异步

兼容性试验发现，官方 Adapter 产生的 LangChain Tool 只有异步调用入口：直接用同步 `agent.invoke()` 会抛出 `NotImplementedError`。

因此只把受影响的用户链路改为：

```text
FastAPI /v1/chat
  -> await AgentRuntime.answer()
  -> await agent.ainvoke()
  -> await MCP Tool
```

CLI 只在进程最外层创建一次事件循环。运营 Agent 和确定性业务 Service 没有跟随改造成异步。原来的同一会话串行约束改用 `asyncio.Lock`，等待期间取消、执行失败和正常完成都会正确归还会话引用并释放锁；同步的兑换确认逻辑通过工作线程执行，避免阻塞事件循环。

### 4.4 MCP 返回值在 Agent 中是什么样

Java MCP 返回的业务数据仍是既有五字段 Envelope。例如：

```json
{
  "success": true,
  "code": "AWARD_FOUND",
  "data": {
    "awardId": 6,
    "name": "智能手环",
    "requiredPoints": 5000
  },
  "message": "奖品查询成功",
  "retryable": false
}
```

官方 Adapter 在真实 Agent 循环里将结果放入一个 `ToolMessage`：

- `content` 是模型可读的 JSON 文本块；
- `artifact.structured_content` 是可由程序读取的结构化 Envelope；
- 不存在的奖品返回业务码 `AWARD_NOT_FOUND`，不被误报为 MCP 协议异常。

## 5. 可观测性

Python Tool 轨迹新增 `transport`：

```json
{
  "tool_name": "get_award_detail",
  "arguments": {"award_id": 6},
  "completed": true,
  "business_success": true,
  "result_code": "AWARD_FOUND",
  "elapsed_ms": 8.21,
  "transport": "mcp"
}
```

轨迹只记录受限参数、耗时和业务码，不记录完整奖品对象或凭据。Java 侧继续记录独立的 MCP `callId`。本轮没有自定义官方 Adapter 的动态请求头，因此 Python `X-Request-ID` 尚未贯穿到 Java MCP 日志；这是当前实验的已知限制，不伪装成已经实现。

健康信息增加：

- `award_detail_transport`：当前选择的模式；
- `mcp_award_tool_ready`：远程 Tool 是否已完成发现和校验。

## 6. 验证证据

### 6.1 Python 定向验证

```powershell
cd D:\工作\incentive-事务消息\agent-service
.\.venv\Scripts\python.exe -m unittest tests.test_config tests.test_mcp_award_tool tests.test_trace tests.test_agent tests.test_runtime tests.test_web tests.test_campaign_workflow tests.test_operator_api
```

结果：`55` 条通过。

这些检查覆盖默认 REST、配置拒绝、MCP 初始化失败、Tool 替换、内部 Service 继续走 REST、轨迹字段，以及会话失败与取消后的锁释放。

### 6.2 真实 Java MCP 与 Agent 验证

```powershell
$env:RUN_MCP_INTEGRATION = "true"
$env:MCP_INTEGRATION_URL = "http://127.0.0.1:18088/mcp"
.\.venv\Scripts\python.exe -m unittest tests.test_mcp_award_integration
```

结果：`2` 条通过。

真实证据包括：

- 已存在奖品和不存在奖品的 MCP Envelope 与 REST 一致；
- Fake Tool-calling Model 驱动真实 LangChain Agent 调用一次 MCP Tool；
- Agent 收到恰好一个 `ToolMessage`；
- 轨迹中恰好一次 `get_award_detail`，且 `transport=mcp`；
- 本次 Tool 执行没有调用 Python 本地 REST 奖品详情入口。

### 6.3 Java 定向验证

```powershell
cd D:\工作\incentive-事务消息\incentive
.\mvnw.cmd -q "-Dtest=AwardQueryMcpConfigurationTest,AwardQueryMcpProtocolTest,AwardQueryMcpToolTest,LoopbackOnlyFilterTest,McpSdkCompatibilityTest" test
```

结果：`8` 条通过，无失败、错误或跳过。30 个固定本地样本中，REST/MCP 成功率与业务契约一致率均为 `100%`；该数据只证明本地协议路径可用，不是生产性能承诺。

## 7. Code Review 结果

评审发现并修正三项边界问题：

1. 旧版 lifespan 在 `runtime.initialize()` 成功后才进入 `try/finally`。如果 MCP 初始化在 ready 前失败，Runtime 已创建的 HTTP、Redis、MySQL 或知识库资源可能无法关闭。修正后初始化本身也位于释放边界内，测试明确构造异常并验证 `runtime.close()` 仍被调用。
2. 初版 Schema 判断把 `minimum=2` 也视为合法正整数约束，但这会错误排除本来合法的 `award_id=1`。现在按 Java `long` 精确校验下界 `1` 和上界 `9223372036854775807`，并拒绝枚举、倍数或其他范围变化。
3. `/v1/chat` 异步化后，响应组装仍同步读取待确认记录。Redis 后端可能因此阻塞事件循环；现在该读取通过工作线程执行，原同步 Service 契约保持不变。

修正后未发现阻塞交付的 `Critical` 或 `High` 问题。剩余限制是：当前只验证一个本地、身份中立、只读 Tool；没有生产鉴权，也没有跨进程统一请求标识。

## 8. 回滚

恢复 REST 不需要改代码或迁移数据。在项目根目录执行：

```powershell
$env:AWARD_DETAIL_TRANSPORT = "rest"; .\start-local.ps1 -RestartAgent -SkipApp
```

该命令只重启 Agent，不重启 Java 和中间件。若 `.env` 中曾写入 `mcp`，也应同步改回 `rest`，保证下次新终端启动仍使用默认路径。
