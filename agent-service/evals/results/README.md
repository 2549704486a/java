# 评测原始结果

本目录保存评测 Runner 生成的 JSON。每个文件包含评测环境、自动评分、最终回答、模型声明的 Tool 调用、实际 Tool 执行轨迹、Fixture 后端调用和完整消息轨迹，不保存 API Key。

结构化 `tool_execution_trace` 不保存完整业务响应，但用于离线审计的 LangChain `trace` 会保留 ToolMessage 内容。提交 Git 的结果应只使用 Fixture 或本地演示数据；真实用户数据必须先脱敏，不能直接进入结果目录。

- `tool_trace_multiskill_20260820.json`：新增四个多 Skill 路由场景的定向验证，结果 `4/4`。
- `tool_trace_full_20260820.json`：接入结构化执行轨迹后的 22 个固定场景全量回归，结果 `22/22`。
