# Java 业务服务 MCP 最小样本

> 这一轮不是把全部 Agent Tool 迁移到 MCP，而是用一个只读奖品查询回答一个更小的问题：现有 Java Web 服务能否在不复制业务逻辑的前提下，同时被 REST 客户端和标准 MCP 客户端调用。

## 1. 最终结构

```text
现有 Python Agent
  -> BusinessApiClient
  -> REST Controller
  -> AgentQueryService

标准 MCP 客户端
  -> Streamable HTTP /mcp
  -> get_award_detail
  -> AgentQueryService
```

两条入口共用同一个 `AgentQueryService`。MCP Tool 没有调用本机 REST，也没有增加 `Capability -> Adapter -> Service` 中间层。

## 2. 为什么只选奖品详情

`get_award_detail` 只接收正整数 `award_id`，没有用户身份，也不修改积分、库存、订单或活动状态。它可以验证 Tool 发现、参数 Schema、结构化结果和错误语义，同时避免把协议试验扩大成鉴权与写操作改造。

```json
{
  "name": "get_award_detail",
  "arguments": {
    "award_id": 6
  }
}
```

业务结果继续使用已有 Envelope：

```json
{
  "success": true,
  "code": "AWARD_FOUND",
  "data": {
    "awardId": 6,
    "awardName": "智能手环"
  },
  "message": "奖品查询成功",
  "retryable": false
}
```

不存在的奖品仍由 `AgentQueryService` 返回 `AWARD_NOT_FOUND`；MCP 层不虚构默认值，也不改写为协议成功业务成功。

## 3. 核心实现

### 3.1 默认关闭

```properties
agent.mcp.enabled=${AGENT_MCP_ENABLED:false}
```

只有显式设置 `AGENT_MCP_ENABLED=true` 时，Spring 才注册 MCP Servlet、Server 和 Tool。不开启时，现有 REST 启动和调用方式不变。

### 3.2 薄 Tool

核心调用只有一层委托：

```java
AgentToolResponse<AwardDetailView> response =
        agentQueryService.getAwardDetail(awardId);
```

Tool 只负责：

- 声明名称、说明和输入/输出 Schema；
- 拒绝缺失、非正数或额外身份参数；
- 调用一次现有 Service；
- 将既有 `AgentToolResponse` 转为 MCP structured content；
- 记录 `callId`、Tool、业务码、成功状态和耗时。

日志不记录完整奖品详情：

```text
MCP callId=<调用标识> tool=get_award_detail code=AWARD_FOUND success=true elapsedMs=8
```

### 3.3 Streamable HTTP

MCP 使用当前 Spring Web 应用内的 `/mcp` Servlet，与 REST 共用进程生命周期、Service Bean、ObjectMapper、数据库连接和日志配置。首版只允许回环地址访问，并同时校验 Host/Origin；这只是本地试验边界，不等于生产鉴权。

## 4. 如何启用

在启动 Java 服务前显式设置环境变量：

```powershell
$env:AGENT_MCP_ENABLED = "true"
mvn spring-boot:run
```

标准 MCP 客户端连接当前 Java 地址的 `/mcp`，例如本地默认服务地址对应 `http://127.0.0.1:8088/mcp`。关闭 PowerShell 窗口或执行下面命令可恢复默认关闭状态：

```powershell
Remove-Item Env:AGENT_MCP_ENABLED
```

当前 Python Agent 不读取这个配置，也没有切换到 MCP。

## 5. 验证证据

定向验证覆盖：

- Maven 依赖树与最小 SDK 生命周期；
- 默认关闭和显式启用的 Spring 上下文；
- 标准 MCP 客户端初始化、Tool 发现和输入 Schema；
- 已存在奖品、不存在奖品、非法 ID 和额外 `user_id`；
- REST 与 MCP 的五个业务 Envelope 字段完全一致；
- 日志摘要不泄露完整奖品数据；
- 既有 `AgentQueryServiceTest`。

结果：MCP 定向测试 `8/8`，既有 Service 测试 `6/6`；评审修正 `callId` 后的协议与日志定向测试 `3/3`。

两次本地、固定 Fixture、稳定连接对照均执行 30 个样本：

| 轮次 | REST 成功率 | MCP 成功率 | 契约一致率 | REST Avg/P95 | MCP Avg/P95 |
| --- | --- | --- | --- | --- | --- |
| 1 | 100% | 100% | 100% | 7.463ms / 9.435ms | 9.594ms / 14.410ms |
| 2 | 100% | 100% | 100% | 7.353ms / 9.476ms | 9.534ms / 20.349ms |

平均额外开销约 `2.1~2.2ms`。P95 在两次运行中波动明显，说明这组本地小样本只适合判断协议开销是否离谱，不能作为生产性能承诺。

## 6. Code Review 与保留决定

评审未发现 `Critical` 或 `High` 问题。发现并修复一个 `Medium` 可观测性问题：原日志没有单次调用标识，并发时难以关联；现在每次调用生成独立 `callId`。

最终决定是保留这个最小样本，理由是：

- 标准 MCP 客户端可以真实发现和调用；
- REST/MCP 共用一份业务实现和 DTO；
- 默认关闭，不改变现有 Agent 和前端；
- 生产代码只增加 MCP 配置与一个薄 Tool；
- 本地额外开销可接受。

剩余风险和非结论：

- 目前没有生产认证、授权和跨网络部署方案；
- 只有一个只读 Tool，不能证明全部 Java 接口都适合 MCP；
- 现有用户 Agent 和运营 Agent 仍走 REST，尚未得到真实第二调用方的复用收益；
- 身份查询和写操作不得照搬本样本，必须另行设计可信身份、权限、幂等和审计。

因此下一步不是继续批量迁移 Tool，而是保留该样本，等待真实调用方需求后再提出独立变更。

## 7. 回滚方式

默认配置已经关闭 MCP。若决定彻底移除，只需删除 MCP 配置、Tool、测试与两个 SDK 依赖；REST Controller、`AgentQueryService`、数据库及 Python Agent 均不需要迁移或回滚数据。
