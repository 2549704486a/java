## Why

Java 服务已经能通过默认关闭的 Streamable HTTP MCP Server 暴露 `get_award_detail`，但当前用户 Agent 仍只通过本地 LangChain Tool 和 `BusinessApiClient` 调用 REST，因此现有证据只证明 MCP Server 可用，尚未证明模型能够发现并真实执行 Java MCP Tool。现在需要用一个身份中立、只读的最小调用完成 Agent 侧纵向闭环，同时避免把 MCP 变成全部后端方法的新 RPC 层。

## What Changes

- 增加默认关闭的 Agent 侧实验配置，仅在显式启用时连接 Java `/mcp`。
- 实验模式下只加载并允许 `get_award_detail`，用远端 MCP Tool 替换模型直接可见的同名本地 Tool；其他用户 Tool、运营 Tool和 Python 业务 Service 继续通过 REST 调用 `BusinessApiClient`。
- Agent 启动或首次构建前验证 MCP Server、Tool 名称和输入 Schema；连接失败、Tool 缺失或契约漂移时明确失败，不静默回退 REST，从而保证实验结果可判定。
- 保留 `AWARD_DETAIL_TRANSPORT=rest` 为默认值，关闭实验后恢复现有行为，不修改 Java REST Controller、业务 Service、数据库和旧事务消息兑换链路。
- 为 REST/MCP 路由选择、远端 Tool 调用和错误结果保留统一请求关联与 Tool 轨迹，并增加真实 Agent 调用的定向验收。
- 先完成 Python MCP SDK/LangChain MCP Adapter 与当前同步 `agent.invoke()` 运行时的兼容性 spike；证据确认官方远程 Tool 仅支持异步调用后，经人工审阅，将受影响的用户 Agent 执行边界有限改为 `ainvoke()`。
- 用户 HTTP 对话入口与 CLI Agent 入口改为异步等待，保持会话内串行；运营 Agent、确定性 Python Service 和 Java REST 基线不随之迁移。

**目标**

- 证明用户问题可以经过“模型选择 Tool -> Python MCP Client -> Java MCP Server -> `AgentQueryService` -> 模型回答”的真实闭环。
- 只迁移对 Agent 有直接价值的能力，不按 Java 方法数量机械创建 MCP Tool。
- 保持默认 REST 基线和现有业务行为可回退、可对照。

**非目标**

- 不迁移积分规划、受控兑换、长期记忆等 Python Service 内部的奖品查询，它们继续走 REST。
- 不增加用户积分、兑换资格、订单、通知或运营能力的 MCP Tool。
- 不设计用户/运营身份委托，不开放任何写操作，不删除 REST。
- 不恢复 Capability、Adapter、独立 Runtime 或通用 MCP 平台。
- 不改造运营 Agent、确定性业务 Service 或无关后台任务的同步执行方式；不在 Tool 内增加后台事件循环或逐次 `asyncio.run()` 桥接。

## Capabilities

### New Capabilities

- `agent-mcp-tool-consumption`: 用户 Agent 可以在显式实验模式下发现并调用允许清单内的 Java MCP Tool，同时保持默认 REST 行为和现有 Tool 轨迹边界。

### Modified Capabilities

无。

## Impact

- `agent-service` 配置、依赖、Agent/Tool 装配，以及用户 Agent HTTP/CLI 执行路径的有限异步化和资源管理。
- 一个只允许 `get_award_detail` 的薄 MCP Client 接入点，以及对应定向测试。
- Java MCP Server 和 REST 业务契约保持不变；前端、运营 Agent、数据库、Redis、RocketMQ 和旧事务消息兑换链路不受影响。
- 需要核对 `langchain-mcp-adapters`、官方 Python MCP SDK与当前 LangChain/Python 版本的兼容组合；版本必须固定并记录来源，不能通过无关框架升级解决冲突。
