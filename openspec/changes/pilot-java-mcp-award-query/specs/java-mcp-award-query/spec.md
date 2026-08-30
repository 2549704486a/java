## Purpose

以一个身份中立、无副作用的奖品详情查询为最小样本，验证现有 Java 业务 Service 可以通过标准 MCP 协议被发现和调用，同时不复制业务规则、不改变 REST 基线，也不提前外放身份相关或高风险能力。

## ADDED Requirements

### Requirement: MCP 奖品查询默认关闭

系统 SHALL 仅在开发者显式启用 MCP 试验配置时注册 MCP 协议入口和奖品查询 Tool；未启用时，现有 Java REST 服务和启动行为保持不变。

#### Scenario: 使用默认配置启动 Java 服务

- **WHEN** Java 服务未配置启用 MCP 试验
- **THEN** 服务不暴露 MCP 协议入口
- **AND** 现有 REST 奖品查询仍按原契约工作

#### Scenario: 在本地显式启用 MCP 试验

- **WHEN** 开发者在本地回环环境显式启用 MCP
- **THEN** 标准 MCP 客户端能够完成初始化并发现 `get_award_detail`
- **AND** 该配置不得被文档描述为已经具备生产鉴权

### Requirement: MCP Tool 直接复用现有 Java Service

`get_award_detail` MCP Tool SHALL 只负责协议参数校验和调用分发，并且每次有效调用只调用一次 `AgentQueryService.getAwardDetail`；系统不得为 MCP 复制奖品查询、错误码、DTO 映射或缓存访问逻辑。

#### Scenario: 查询已存在的奖品

- **WHEN** MCP 客户端使用正整数奖品 ID 调用 `get_award_detail`
- **AND** 对应奖品存在且当前业务 Service 能够读取
- **THEN** MCP Tool 返回成功的结构化 `AgentToolResponse`
- **AND** `data` 使用当前 `AwardDetailView` 的字段和语义
- **AND** Java Service 只被调用一次

#### Scenario: 查询不存在的奖品

- **WHEN** MCP 客户端使用正整数奖品 ID 调用 `get_award_detail`
- **AND** 当前业务 Service 找不到对应奖品
- **THEN** MCP Tool 原样保留 Service 的失败业务码、消息和不可重试语义
- **AND** 协议层不得虚构默认奖品或把失败改写为成功

#### Scenario: 奖品 ID 不符合输入 Schema

- **WHEN** MCP 客户端传入缺失、非整数或非正数的奖品 ID
- **THEN** MCP 协议参数校验拒绝调用
- **AND** `AgentQueryService` 不被执行

### Requirement: MCP 与 REST 的业务契约保持一致

系统 SHALL 保留现有 REST 奖品详情查询，并对同一固定业务数据保证 REST 与 MCP 返回的 `success`、`code`、`data`、`message` 和 `retryable` 语义一致。

#### Scenario: 对照成功结果

- **WHEN** 测试分别通过 REST 与 MCP 查询同一个存在的奖品
- **THEN** 两种入口的结构化业务 Envelope 完全一致

#### Scenario: 对照不存在结果

- **WHEN** 测试分别通过 REST 与 MCP 查询同一个不存在的奖品
- **THEN** 两种入口的结构化业务 Envelope 完全一致

### Requirement: 首版 MCP 不暴露身份相关和写操作能力

首版 MCP Server MUST 只暴露经过本变更批准的身份中立只读奖品查询，不得注册用户私有查询、运营私有查询或任何业务写操作。

#### Scenario: 客户端发现 MCP Tools

- **WHEN** 标准 MCP 客户端列出服务端 Tool
- **THEN** 列表包含 `get_award_detail`
- **AND** 不包含用户积分、任务、订单、兑换资格、兑换提交、活动提交、审核、发布或指标写入能力

#### Scenario: 模型尝试提供用户身份

- **WHEN** 调用方尝试在 `get_award_detail` 参数中增加用户 ID、运营 ID 或权限字段
- **THEN** 这些字段不属于 Tool Schema，也不能扩大 MCP 能力范围

### Requirement: MCP 协议入口可定位但不泄露完整业务数据

系统 SHALL 为每次 MCP Tool 执行记录可关联的 Tool 名称、成功状态、业务结果码和耗时，并且不得在协议审计日志中记录完整奖品响应、连接凭据或内部异常堆栈。

#### Scenario: MCP 奖品查询完成

- **WHEN** `get_award_detail` 返回成功或业务失败结果
- **THEN** 服务端日志包含 Tool 名称、成功状态、业务结果码和耗时
- **AND** 日志不包含完整 `AwardDetailView` 内容

### Requirement: MCP 是否扩展必须由对照证据决定

系统 SHALL 在固定数据和同一本地环境下记录 REST/MCP 契约一致性、调用成功率与稳定连接耗时；在证据完成前，不得把其他能力迁移到 MCP。

#### Scenario: 最小样本尚未完成验收

- **WHEN** 依赖兼容性、协议发现、契约一致性或定向测试任一项未完成
- **THEN** 项目文档继续将 MCP 标记为试验或未落地
- **AND** 不新增第二个 MCP 业务 Tool

#### Scenario: 最小样本验收完成

- **WHEN** Tool 发现、成功与不存在场景、REST/MCP 契约对照、Code Review 和定向测试均通过
- **THEN** 项目可以保留该最小 Tool
- **AND** 是否新增身份相关或运营能力仍需单独提出包含鉴权边界的新变更
