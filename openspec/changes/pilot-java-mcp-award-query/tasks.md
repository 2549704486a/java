## 1. 依赖兼容性与基线

- [x] 1.1 输出当前 Java effective POM 和 Spring Boot 依赖树，确认父版本与显式 Starter 版本混用的实际结果；如需收敛，只保留父 BOM 管理并运行现有 `AgentQueryServiceTest`。
- [x] 1.2 分别核对兼容的 Spring WebMVC MCP Server Starter 与官方 Java MCP SDK，选择不要求升级 Spring Boot 主次版本、不引入第二套 Web 框架的最小方案；将版本、选择理由和未采用方案补充到 `design.md`。
- [x] 1.3 增加最小依赖后执行 Maven 依赖树和 Spring 上下文烟雾测试；若无法得到兼容组合，记录阻塞并停止，不继续编写协议代码。

## 2. Java MCP 薄入口

- [x] 2.1 增加默认关闭的 MCP 配置，并用定向上下文测试证明未显式启用时不注册 MCP 端点和 Tool。
- [x] 2.2 实现 `get_award_detail` MCP Tool：只定义协议名称、说明和正整数参数 Schema，直接调用一次 `AgentQueryService.getAwardDetail`，不新增 Capability、Adapter、DTO 副本或业务规则。
- [x] 2.3 为 MCP 调用记录 Tool 名称、业务结果码、成功状态和耗时，验证日志不包含完整响应和敏感配置。

## 3. 协议与契约验证

- [x] 3.1 使用标准 MCP 测试客户端验证初始化、Tool 列表和 `get_award_detail` 输入 Schema，不创建生产 Python MCP Client 封装。
- [x] 3.2 使用固定 Java Fixture 验证已存在奖品和不存在奖品两个场景，并断言 MCP 结构化结果中的业务 Envelope 与 REST 结果一致。
- [x] 3.3 验证无效 `award_id` 在协议参数层被拒绝，且 MCP Server 未暴露用户积分、订单、兑换、活动审核或发布等未授权能力。
- [x] 3.4 保持现有 REST Controller 和 Python `BusinessApiClient` 不变，运行受影响的 Java Service、Controller 与 MCP 定向测试；仅在依赖收敛影响整个 Spring 上下文时运行 Java 模块测试，不执行无关 Python/前端全量回归。

## 4. 对照、评审与去留决策

- [x] 4.1 在同一本地环境和固定数据下，使用稳定连接分别执行 REST 与 MCP 查询，记录成功率、结构化契约一致率、平均耗时和 P95；明确该结果不是生产性能承诺。
- [x] 4.2 按根目录 `CODE_REVIEW.MD` 完成自评审，重点检查动态事实来源、薄入口、默认关闭、无身份参数、无写操作、错误语义和工作树隔离；修复所有 `Critical`、`High` 问题。
- [x] 4.3 根据证据作出明确决定：若契约一致且依赖、代码与调用开销可接受则保留最小样本；否则完整删除 MCP 试验代码，不把“协议能启动”当作保留理由。
- [x] 4.4 只有保留决定成立后，新增一份 `docs/agent-design/` 实施文档，更新 P4.3 课程覆盖、当前里程碑和任务日记；使用中文提交信息，只暂存本变更及可随功能提交的治理文档。
- [x] 4.5 使用隔离安装目录中的 OpenSpec `1.10.0` 执行 `validate pilot-java-mcp-award-query --strict`，严格校验通过；CLI 仍未加入全局 `PATH`。
