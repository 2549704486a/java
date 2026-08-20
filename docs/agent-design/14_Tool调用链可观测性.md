# Tool 调用链可观测性

> 只看最终回答无法判断 Agent 是正确调用了一次组合 Skill，还是重复调用多个基础 Tool 后碰巧答对。本阶段把“模型想调用什么、代码实际执行什么、业务返回什么、每一步花多久”拆成可查询证据，并让线上日志和离线评测使用同一种轨迹语义。

## 1. 需要回答的问题

一次 Agent 请求结束后，应能够回答：

- 模型选择了哪些 Tool，传入了什么参数？
- 这些 Tool 是否真正执行完成，而不只是出现在模型声明中？
- Tool 返回的业务结果码是什么？
- 总耗时高是模型推理慢，还是 Java 查询或组合 Skill 慢？
- 某次异常能否通过 `request_id` 从 HTTP 日志定位到 Tool 轨迹？

## 2. 轨迹结构与采集流程

每个 `ToolExecutionTrace` 包含：

| 字段 | 含义 |
| --- | --- |
| `sequence` | 本次请求中的执行顺序 |
| `tool_name` | 实际进入的 Tool 或 Skill 名称 |
| `arguments` | 模型可控的结构化参数，不重复记录绑定的用户身份 |
| `completed` | Python 调用是否正常返回 |
| `business_success` | 基础接口明确返回的业务成功标记；多状态 Skill 为 `null` |
| `result_code` | Java `code` 或 Skill `status` |
| `elapsed_ms` | Tool/Skill 自身耗时，不包含前后模型推理 |
| `error_type` | 未完成时的异常类型，不保存异常堆栈和消息正文 |

```text
FastAPI 生成或接收 request_id
  -> AgentRuntime 传入 run_agent
  -> capture_tool_trace 建立请求级上下文
  -> Tool/Skill 通过 execute_traced 执行
  -> BusinessApiClient 透传 X-Request-ID 并记录下游路径
  -> 只提取参数、结果码和耗时
  -> run_agent 输出一条 agent_tool_trace 日志
```

轨迹上下文使用 `ContextVar`，Agent 实例可以跨请求复用，但每次请求的事件仍彼此隔离；`ToolTraceSession` 内部使用锁，允许未来并行 Tool 安全追加事件。

## 3. 为什么不直接返回给用户

普通用户只需要业务答案和 `request_id`，不需要知道内部 Tool 名称。结构化执行轨迹只进入服务端日志和评测结果，避免泄露实现细节，也避免响应契约因内部编排变化而频繁修改。

服务端结构化轨迹不保存用户问题正文、API Key、完整积分/任务/奖品响应和内部异常消息。需要深入排查时，可使用 `request_id` 继续关联业务接口日志。

## 4. 评测器升级

原评测器从 `AIMessage.tool_calls` 判断模型声明，无法证明 Tool 已真正完成。现在同时保存：

- `declared_tool_calls`：模型声明，供审计模型意图。
- `tool_execution_trace`：代码真实执行，作为 Tool 选择与参数评分依据。
- `backend_calls`：Fixture 记录的 Java 方法路径，验证组合 Skill 内部编排。
- `trace`：完整 LangChain 消息轨迹，保留原始证据。

其中 `trace` 可能包含 ToolMessage 的完整输出，只适用于受控的 Fixture、本地演示数据或已脱敏数据；线上日志只记录结构化执行摘要。

新增 `tool_execution` 检查；只要某个实际 Tool 抛出异常未完成，该项即失败。汇总区按 Tool 输出调用次数、执行失败数、平均耗时和最大耗时。

## 5. 验证证据

- 离线单元测试：`29/29`。
- 新增多 Skill 定向用例：`4/4`。
- 22 个固定场景全量回归：`22/22`，其中多 Skill 路由 `7/7`。
- 真实 HTTP：`request_id=trace-live-004`，请求总耗时 `4988.45ms`；两次 Java 查询分别耗时 `8.94ms` 和 `12.13ms`，只执行一次 `recommend_awards(limit=1)`，Skill 总耗时 `21.56ms`，结果码为 `RECOMMENDATIONS_READY`。

这组数据不能代表生产性能，但能证明请求 ID 关联、实际执行采集和模型/Tool 耗时拆分已经生效。

## 6. 代码索引

| 代码 | 作用 |
| --- | --- |
| `agent-service/app/trace.py` | 请求级上下文、轨迹数据结构和统一执行包装 |
| `agent-service/app/tools.py` | 七个 Tool/Skill 的采集入口 |
| `agent-service/app/agent.py` | 建立轨迹作用域并输出结构化日志 |
| `agent-service/app/api_client.py` | 向 Java 接口透传请求 ID，并关联路径、重试和耗时日志 |
| `agent-service/evals/runner.py` | 使用实际执行轨迹评分并聚合 Tool 指标 |
| `agent-service/tests/test_trace.py` | 成功、异常和真实 Skill 接入测试 |
