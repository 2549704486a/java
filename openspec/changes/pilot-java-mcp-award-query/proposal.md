## Why

当前用户 Agent、运营 Agent、前端接口和评测 Runner 都通过 Python `BusinessApiClient` 调用 Java REST 接口。业务闭环已经形成了多个调用场景，但 Java 业务能力仍只能通过项目自定义 HTTP 路径接入，尚未验证标准 MCP 客户端能否直接发现并复用同一份业务能力。

项目此前在 Python 侧完整实现过 MCP，但同时增加了统一 Capability、独立 Runtime、安全中间件、MCP Client 和 LangChain 适配器。虽然功能和测试完整，协议层却包围并重复了已有调用路径，因此已整体回滚。本次不恢复旧实现，而是用一条最小纵向切片验证另一种方向：MCP Tool 位于 Java 业务事实源旁边，直接调用现有 Service，不增加新的业务能力层。

首个样本选择奖品详情查询。它已经由 `AgentQueryService.getAwardDetail` 实现，是只读且不依赖用户身份的动态业务事实，既能避免高风险写操作，也能真实验证 MCP 的能力发现、参数 Schema、结构化结果和 REST 契约一致性。

## What Changes

- 在 Java 服务中增加默认关闭、显式启用的 MCP Streamable HTTP 入口。
- 只暴露一个只读 Tool：`get_award_detail`，直接委托现有 `AgentQueryService.getAwardDetail`。
- MCP 与 REST 共用现有 `AgentToolResponse<AwardDetailView>` 业务结果，不复制查询、错误码或字段转换逻辑。
- 保留当前 Python LangChain Tool 与 `BusinessApiClient` REST 调用作为基线，本轮不切换用户 Agent 的生产调用路径。
- 增加协议级定向验证：Tool 发现、成功查询、奖品不存在、默认关闭和 REST/MCP 结果一致。
- 对比稳定连接下 REST 与 MCP 的契约、额外耗时和实现复杂度，再决定是否保留并扩展第二个能力。

## Goals And Non-Goals

**目标**

- 验证 Java 业务 Service 能否通过薄 MCP 协议入口被标准客户端发现和调用。
- 证明 MCP 入口没有复制业务规则，也没有改变现有 REST 行为。
- 获得是否继续扩展 MCP 的代码规模、契约一致性和调用开销证据。
- 为后续身份相关或运营能力的独立设计建立可复查的最小样本。

**非目标**

- 不把全部 LangChain Tool 迁移为 MCP Tool。
- 不开放积分、兑换资格、订单等需要可信用户身份的查询。
- 不开放兑换、活动提交、审核、发布、指标写入等任何写操作。
- 不实现 MCP Resources、Prompts、stdio、独立 MCP 进程或通用 Capability 平台。
- 不在本轮让用户 Agent 改走 MCP，也不删除现有 REST Controller 和 `BusinessApiClient`。
- 不把本地协议实验包装成生产鉴权、跨网络部署或性能结论。

## Evidence And Assumptions

**已确认事实**

- `AgentQueryController.getAwardDetail` 与多个 Python Tool/Service 已复用 `AgentQueryService.getAwardDetail` 返回的稳定 `AgentToolResponse`。
- 当前 Java 工程没有 MCP 依赖或 MCP 源码。
- 当前 Maven 配置存在 Spring Boot 父版本与单个 Starter 显式版本不一致的问题，新增 MCP 依赖前必须先验证兼容性，不能直接升级整个框架。
- 当前工作树有一组尚未提交的 Skill/Service 纠偏改动；本变更不得覆盖或回滚这些文件。
- 旧 MCP 实现位于 Python 侧，并曾引入 Capability、Runtime、Client 和多层适配；当前工作树已不保留这些实现。
- 路线图 P4.3 要求先选择只读最小样本、保留现有 Tool 基线，并用复用收益证据决定是否扩展。

**待实现阶段验证的假设**

- 存在与当前 Spring Boot 基线兼容、无需升级整个应用的 Java MCP Server 依赖组合。
- Java MCP Tool 可以直接返回现有 record DTO，并生成客户端可用的结构化结果 Schema。
- 单个薄 Tool 和必要配置的维护成本明显低于已回滚的 Python MCP 模块。

若第一个假设不成立，本变更应停在依赖兼容性结论，不得为了展示 MCP 顺带升级整个 Spring Boot、MyBatis、RocketMQ 或 Sentinel 技术栈。

## Capabilities

### New Capabilities

- `java-mcp-award-query`: 通过默认关闭的 Java MCP 入口发现并调用只读奖品详情 Tool，同时保持与现有 REST 业务契约一致。

### Modified Capabilities

无。现有 REST 奖品详情查询和 Python Agent 调用路径保持不变。

## Impact

- Java Maven 依赖与 MCP 配置。
- 一个直接委托 `AgentQueryService` 的 Java MCP Tool 入口。
- Java 侧协议级和契约对照测试。
- 若最小样本验收通过，再更新产品事实、P4.3 路线图、设计文档和任务日记。
- 不修改数据库、Redis、RocketMQ、旧事务消息兑换链路、Python Tool 行为和前端页面。
