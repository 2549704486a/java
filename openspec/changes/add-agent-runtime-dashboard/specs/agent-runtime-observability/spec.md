## Purpose

为运营人员提供一套可授权、可解释、可下钻的 Agent 运行数据视图，用于判断服务是否正常、请求耗时分布以及 Tool 调用结果，同时避免把运行完成误报为回答正确或业务成功。

## ADDED Requirements

### Requirement: 记录已认证的 Agent 请求
系统 SHALL 为通过身份认证并进入用户 Agent 或运营 Agent 运行时的每个请求记录唯一的运行摘要，摘要至少包含请求 ID、Agent 类型、开始与结束时间、终态、端到端耗时、Tool 调用数以及可获得的模型用量。

请求终态 SHALL 只有以下两种运行语义：`COMPLETED` 表示 Agent 正常返回了一个响应，`FAILED` 表示运行时未能正常返回响应；`COMPLETED` MUST NOT 被解释为回答正确、兑换成功或活动执行成功。

#### Scenario: 用户 Agent 正常返回
- **WHEN** 一个通过认证的用户对话请求进入 Agent 并正常返回回答
- **THEN** 系统记录一条 `agent_type=USER`、`status=COMPLETED` 的请求摘要
- **THEN** 该记录的请求 ID 与本次 HTTP 请求使用的请求 ID 一致

#### Scenario: 运营 Agent 运行失败
- **WHEN** 一个通过认证的运营对话请求在 Agent 运行期间抛出未恢复异常
- **THEN** 系统记录一条 `agent_type=OPERATOR`、`status=FAILED` 的请求摘要
- **THEN** 记录仅包含可归类的错误类型，不包含异常堆栈或敏感错误正文

#### Scenario: 身份认证前被拒绝
- **WHEN** 请求因用户令牌或运营令牌无效而未进入 Agent 运行时
- **THEN** 系统不把该请求计入 Agent 运行数据

### Requirement: 最小化运行观测数据
系统 SHALL 只持久化生成运行指标和请求轨迹所需的摘要字段。系统 MUST NOT 在观测表中保存用户提问、模型回答、Tool 完整参数、Tool 返回正文、访问令牌、用户 ID、运营人员 ID或会话 ID。

#### Scenario: 查看单次请求轨迹
- **WHEN** 有权限的运营人员查看一条请求详情
- **THEN** 响应可以包含请求 ID、Agent 类型、时间、耗时、状态、用量摘要和 Tool 摘要
- **THEN** 响应不包含对话正文、业务对象正文或调用者身份标识

### Requirement: 如实表达模型用量缺失
系统 SHALL 汇总当前模型提供的输入 Token、输出 Token 和模型调用次数。当模型或调用链未提供可靠用量元数据时，系统 SHALL 将对应 Token 字段记录并展示为未知，而不是写成或展示为零。

#### Scenario: 模型返回完整用量
- **WHEN** 一次请求中的模型调用均返回可靠用量元数据
- **THEN** 请求记录包含本次请求各模型调用累计后的输入和输出 Token
- **THEN** 汇总结果将该请求计入 Token 覆盖请求数

#### Scenario: 模型未返回用量
- **WHEN** 一次请求没有可靠的 Token 用量元数据
- **THEN** 请求记录的输入和输出 Token 为未知
- **THEN** 看板显示“暂无用量数据”或等价表达，不将其显示为 `0`

### Requirement: 保留有明确语义的 Tool 轨迹
系统 SHALL 按调用顺序记录每次 Tool 调用的 Tool 名称、传输方式、耗时、是否执行完成、可选业务结果、结果码和可归类错误类型。没有统一业务状态的 Tool SHALL 将业务结果记录为未知，不得伪造成业务失败。系统 SHALL 分别计算 Tool 执行完成率与业务成功率，不得将两者合并为一个含义模糊的“成功率”。

#### Scenario: Tool 完成但业务拒绝
- **WHEN** Tool 正常完成调用但返回库存不足、条件不满足或其他业务失败
- **THEN** 轨迹显示该 Tool 已执行完成但业务未成功
- **THEN** 该调用计入执行完成率的分子，但不计入业务成功率的分子

#### Scenario: Tool 调用异常中断
- **WHEN** Tool 因超时、连接失败或未处理异常而没有执行完成
- **THEN** 轨迹显示 `completed=false`
- **THEN** 轨迹只暴露可归类错误类型，不暴露异常正文和调用参数

#### Scenario: Tool 完成但没有业务状态
- **WHEN** Tool 正常完成但返回结果没有可解释的业务成功字段
- **THEN** 轨迹显示该 Tool 已执行完成且业务结果未知
- **THEN** 该调用不进入 Tool 业务成功率的分子或分母

### Requirement: 提供口径固定的运行汇总
系统 SHALL 支持 `24h`、`7d` 和 `30d` 三个固定时间窗口，并按请求开始时间统计请求总数、完成数、失败数、完成率、平均端到端耗时、P95 端到端耗时、Token 汇总及覆盖请求数、Tool 调用汇总和时间趋势。

完成率 SHALL 使用 `COMPLETED 请求数 / 请求总数`；Tool 执行完成率 SHALL 使用 `completed=true 的调用数 / Tool 调用总数`；Tool 业务成功率 SHALL 使用 `business_success=true 的调用数 / completed=true 且业务结果已知的调用数`。P95 SHALL 使用按耗时升序排列后的最近秩方法计算。所有比率响应 SHALL 同时返回分子和分母。

#### Scenario: 查询最近七天汇总
- **WHEN** 有权限的运营人员选择 `7d`
- **THEN** 系统只统计当前时刻向前七天内开始的已持久化请求
- **THEN** 返回整体指标、按 Agent 类型拆分的指标、按 Tool 名称拆分的指标和按天聚合的趋势

#### Scenario: 时间窗口内没有请求
- **WHEN** 所选时间窗口内没有 Agent 请求记录
- **THEN** 系统返回有效的空汇总而不是服务错误
- **THEN** 比率与分位耗时显示为暂无数据，不伪造为百分之零或零毫秒

### Requirement: 支持最近请求和轨迹下钻
系统 SHALL 提供按时间倒序、带上限分页的最近请求列表，并允许按请求 ID 读取一条请求摘要及其按序排列的 Tool 轨迹。列表 SHALL 支持按 Agent 类型和运行终态筛选；单页数量 MUST NOT 超过 100。

#### Scenario: 从列表下钻请求
- **WHEN** 有权限的运营人员在最近请求列表中选择一条记录
- **THEN** 系统返回该请求摘要和按 `sequence` 升序排列的 Tool 轨迹

#### Scenario: 请求记录不存在
- **WHEN** 运营人员查询不存在或已经超过留存期的请求 ID
- **THEN** 系统返回明确的未找到结果
- **THEN** 系统不使用其他请求的数据进行替代

### Requirement: 运行数据受独立运营权限保护
系统 SHALL 只允许已认证且拥有 `agent:observe` 权限的运营人员访问 Agent 运行汇总、请求列表和请求详情。活动读取、草案审核或发布权限 MUST NOT 自动授予 Agent 运行数据访问权。

#### Scenario: 有专用权限的运营人员访问
- **WHEN** 运营人员身份有效且包含 `agent:observe`
- **THEN** 系统允许其读取 Agent 运行数据

#### Scenario: 只有活动读取权限
- **WHEN** 运营人员身份有效但只有 `campaign:read` 而没有 `agent:observe`
- **THEN** 系统拒绝读取 Agent 运行数据
- **THEN** 响应不泄露汇总值或请求是否存在

### Requirement: 观测故障不得破坏 Agent 主流程
系统 SHALL 将观测数据写入视为非业务关键旁路。观测存储不可用、写入超时或清理失败时，系统 SHALL 记录可定位告警，但 MUST NOT 将原本可以正常返回的 Agent 请求改为失败。

#### Scenario: 回答成功但观测写入失败
- **WHEN** Agent 已正常生成回答而观测存储写入失败
- **THEN** 调用方仍收到原 Agent 回答
- **THEN** 服务日志记录请求 ID和观测写入失败类别

### Requirement: 看板明确展示来源和指标边界
运营工作台 SHALL 提供 Agent 运行数据区域，允许选择时间窗口、查看汇总与趋势、查看 Tool 指标及下钻最近请求。界面 SHALL 明示数据来源为运行观测记录，并说明运行完成率不代表回答正确率或业务成功率。

离线评测成绩、活动收益漏斗和模拟数据 MUST NOT 混入本看板的线上运行汇总；若未来在同一页面展示，必须使用独立区域和显式数据来源标签。

#### Scenario: 打开 Agent 运行数据区域
- **WHEN** 有权限的运营人员进入该区域
- **THEN** 界面展示所选时间窗口对应的运行数据、数据更新时间和口径说明
- **THEN** 界面不把运行完成率命名为“回答正确率”或“业务成功率”

#### Scenario: 看板查询失败
- **WHEN** 运行数据接口暂时不可用
- **THEN** Agent 对话与活动工作流仍可继续使用
- **THEN** 看板区域独立显示加载失败和可重试操作

### Requirement: 限制查询范围并执行留存清理
系统 SHALL 默认保留最近 30 天的 Agent 运行摘要和 Tool 轨迹，并定期删除超过留存期的数据。查询接口 SHALL 拒绝超过最大留存范围的自定义查询；本能力 SHALL NOT 解析或回填启用前的历史日志。

#### Scenario: 功能首次启用
- **WHEN** 观测表已初始化但尚未产生新 Agent 请求
- **THEN** 看板显示空状态并说明数据从功能启用后开始累计

#### Scenario: 数据超过留存期
- **WHEN** 请求摘要和关联 Tool 轨迹超过配置的留存天数
- **THEN** 系统在清理周期内删除请求摘要及其关联 Tool 轨迹
