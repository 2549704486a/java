## Context

当前真实调用链是：

```text
模型
  -> Python LangChain Tool
  -> BusinessApiClient
  -> Java REST Controller
  -> AgentQueryService
  -> Mapper / MySQL / Redis
```

旧 MCP 方案在 Python 侧新增统一 Capability、MCP Server、MCP Client、独立 Runtime、安全中间件和 LangChain 适配器。它证明了协议可以运行，但没有第二个独立业务系统需要这套平台，反而增加了多层转发和重复维护，因此被整体回滚。

本次只验证下面这条并行入口：

```text
MCP 协议客户端
  -> Java MCP Tool
  -> AgentQueryService
  -> Mapper / MySQL / Redis

现有 Python Agent
  -> BusinessApiClient
  -> Java REST Controller
  -> AgentQueryService
```

REST Controller 与 MCP Tool 都是薄入口，业务事实仍只有 `AgentQueryService` 一份实现。

## Goals / Non-Goals

**Goals:**

- 用最少代码完成 Java MCP Server 的真实协议发现与调用。
- 让 MCP 与 REST 对同一业务输入返回等价的业务 Envelope。
- 默认不改变现有进程的对外能力和用户 Agent 调用路径。
- 以实际代码、协议测试和调用对照决定是否继续扩展。

**Non-Goals:**

- 不建立 `MCP -> Capability -> Adapter -> Service` 调用链。
- 不为一个 Tool 创建独立业务接口、DTO 副本或 Python MCP Client 封装。
- 不在首版处理用户身份、运营权限和高风险写操作。
- 不同时实现 Tool、Resource、Prompt 和两种 Transport 来追求课程覆盖。

## Decisions

### 1. MCP Server 位于 Java 业务事实源，而不是 Python Agent 进程

奖品详情的业务规则和动态数据均由 Java `AgentQueryService` 提供。MCP Tool 直接注入该 Service，并原样返回 `AgentToolResponse<AwardDetailView>`。协议层只负责 Tool 名称、说明、输入 Schema 和调用分发。

不新增 Capability 或 Adapter：当前只有 REST 与 MCP 两个入站协议，它们可以并列调用同一个 Service；额外抽象并不会减少业务实现数量。

**备选方案 A：恢复旧 Python MCP Server。** 可以复用历史代码，但会重新引入已证明没有业务价值的 Runtime、Client 和适配层，不采用。

**备选方案 B：让 Java MCP Tool 调用本机 REST Controller。** 表面上复用 HTTP 契约，实际增加一次无意义的网络跳转，并让 Java 自己调用自己，不采用。

### 2. 首版只暴露 `get_award_detail`

输入只包含正整数 `award_id`；输出使用现有 Envelope：

```json
{
  "success": true,
  "code": "AWARD_FOUND",
  "data": {
    "awardId": 6,
    "awardName": "智能手环"
  },
  "message": "奖品信息读取成功",
  "retryable": false
}
```

示例只展示核心字段，实际字段以当前 `AwardDetailView` 为准，不在 MCP 层重新定义 DTO。

选择它的原因：

- 已有确定性 Service 和测试基础；
- 不需要客户端传入用户身份；
- 没有业务副作用；
- 成功与不存在两种语义都能用于协议对照；
- 当前用户 Agent 的 REST Tool 可以作为不变基线。

用户积分、任务、兑换资格和订单都依赖可信用户身份。活动快照、历史和漏斗属于运营数据，也需要服务端权限模型。它们不因为“同样是查询”就在本轮外放。

### 3. 使用 Streamable HTTP，不实现 stdio 和独立 Runtime

目标是验证现有 Java 服务能否同时作为业务服务和 MCP Server 被其他进程调用，因此使用 Streamable HTTP。MCP 与 REST 共用 Spring 应用生命周期、Service Bean、数据库连接和日志配置。

stdio 更适合由桌面客户端拉起本地子进程，会为当前 Java Web 应用增加第二种启动方式；独立 Runtime 则会重新制造资源装配和生命周期代码。本轮均不采用。

### 4. 默认关闭，只作为本地显式启用的协议实验

MCP 入口默认不启用。开发者显式打开配置后才注册协议端点和 Tool，现有启动流程、REST 客户端与前端不受影响。

首版 Tool 不包含用户数据和写操作，但仍不把“无业务敏感参数”误写成“具备生产安全”。本地验证使用回环地址；若后续要跨主机提供身份相关或运营能力，必须先建立独立的认证、授权、来源限制和审计设计。

### 5. 依赖选择先做兼容性 Spike，不顺带升级技术栈

优先评估与当前 Spring Boot 基线兼容的 Spring WebMVC MCP Server Starter，因为它可以用少量配置和注解生成 Tool Schema。若没有兼容版本，则评估官方 Java MCP SDK的 WebMVC/Servlet Transport。

选择标准：

1. 不要求在本变更中升级 Spring Boot 主次版本；
2. 不引入第二套 Web 框架；
3. 支持 Java 17、Streamable HTTP 和结构化 Tool 结果；
4. 能用现有 Spring Bean 直接注册 Tool；
5. 依赖树不产生已知冲突，最小 Spring 上下文测试能够启动。

如果两个方案都不满足，应记录阻塞并停止，而不是自研 MCP 协议或大规模升级依赖。

当前 `pom.xml` 中 Spring Boot 父版本与一个 Starter 显式版本不一致。实现前先用 effective POM 和 dependency tree 确认实际解析结果；如需收敛，应以父 BOM 为唯一版本来源，并把该调整作为可独立验证的最小改动。

**Spike 结论（2026-08-30）：**

- 不采用 Spring AI MCP Server Starter。Spring AI 1.0.x 的官方基线要求 Spring Boot 3.4.x 或 3.5.x，引入它会把一次协议试验扩大成框架升级。
- 采用官方 MCP Java SDK `0.18.4` 的 `mcp-core` 与 `mcp-json-jackson2`，直接使用 Servlet Streamable HTTP Transport，不引入 WebFlux 或独立 Runtime。
- `spring-boot-starter` 原有显式 `3.3.2` 已移除，所有 Spring Boot 组件统一由父 BOM 管理为 `3.2.3`；原有单独锁定的 Jackson JSR-310 模块也改由 BOM 管理。
- 实际依赖树为 Spring Boot `3.2.3`、Reactor `3.6.3`、Jackson `2.15.4` 与 MCP SDK `0.18.4`。SDK 发布时声明的部分基础库版本更新，因此这不是官方列出的组合，只能视为本项目的实测兼容组合。
- 最小生命周期测试已证明 Jackson Mapper、Servlet Streamable HTTP Transport、MCP Server、Tool Schema 与结构化结果可以创建并正常关闭。仍需通过 Spring Servlet 上下文和真实协议客户端测试，才能确认 HTTP 集成成立。

未选择 SDK `2.0.1`，因为它对 Jackson 等基础依赖的版本跨度更大，无法给当前 Boot 3.2 项目带来与试验目标相称的收益；也未选择较旧且已停止维护的 SDK 版本来换取表面上的依赖接近。

### 6. 契约一致指业务结果一致，不要求协议外壳字节一致

REST 和 MCP 传输格式不同，比较时提取结构化业务结果中的 `success`、`code`、`data`、`message`、`retryable`。以下场景必须一致：

- 已存在奖品；
- 不存在奖品。

无效参数由 MCP 输入 Schema 在进入 Service 前拒绝，属于协议参数校验，不要求与 REST 路径变量的错误页面一致。

### 7. 不编写生产 Python MCP 适配层

协议验证使用标准 MCP 测试客户端或 Inspector，评测代码只负责发起调用并比较结构化结果，不向应用层提供 `McpBusinessApiClient`。首版用户 Agent 继续走 REST，避免在收益尚未成立时同时维护两个生产调用路径。

只有后续明确选择某个 Agent 能力迁移到 MCP，才为该调用方增加最薄的标准客户端集成，并删除对应的重复 REST Tool 路径，而不是长期双写。

### 8. 可观测性只记录协议入口必要信息

每次 MCP Tool 调用记录 Tool 名称、结果码、成功状态和耗时，不记录完整奖品响应。若协议运行时能够取得调用关联 ID，则透传到现有日志上下文；不能取得时生成本次调用标识，但不为首版搭建独立审计平台。

## Risks / Trade-offs

- **依赖兼容性：**当前 Spring Boot 版本混用，MCP Starter 可能要求更高版本。缓解方式是先做依赖 Spike，并禁止在本变更中大规模升级框架。
- **样本过小：**一个 Tool 只能证明纵向路径可行，不能证明整套 Agent 应迁移。验收结论必须限制在该样本，不直接更新为“MCP 已全面落地”。
- **双入口维护：**REST 与 MCP 同时存在。通过直接复用 Service 和结构化契约对照控制漂移；若后续没有第二个 MCP 调用方，应删除试验入口。
- **安全边界：**默认关闭和本地回环只适合验证，不替代生产鉴权。身份相关与运营数据继续留在现有受控入口。
- **协议开销：**MCP 会比 Service 直调增加分发和序列化成本。记录稳定连接下的对照数据，但不把本地结果外推为生产性能。
- **工作树隔离：**当前存在未提交的 Skill/Service 纠偏改动。实现和提交时必须只暂存本变更文件，不能覆盖或夹带无关改动。

## Migration Plan

1. 完成依赖兼容性 Spike，确定使用的官方实现并记录选择依据。
2. 在默认关闭配置下增加 Java MCP Server 和一个薄 Tool。
3. 用定向测试验证默认关闭、Tool 发现、成功和不存在结果。
4. 使用同一数据分别调用 REST 与 MCP，比较结构化业务结果和本地额外耗时。
5. 按 `CODE_REVIEW.MD` 检查协议边界、动态事实来源、错误语义和未授权能力暴露。
6. 若最小样本成立，更新设计事实、路线图和任务日记，并保留该能力；若依赖或维护成本不合理，删除试验代码，只保留结论。

回滚不涉及数据库和业务数据：关闭配置或移除 MCP 依赖、Tool 注册与测试即可，REST 和 Python Agent 始终保持可用。
