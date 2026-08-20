# 第一轮 Agent 评测方案

> 本轮只回答一个问题：当前最小 Agent 能否依据可信工具完成积分查询与规划，并在异常和越权请求下保持正确边界。它不是性能压测，也不评测尚未实现的 RAG、记忆、MCP、多 Agent 和自动兑换。

## 1. 评测层次

| 层次 | 目标 | 数据来源 |
| --- | --- | --- |
| 单元测试 | 验证 Skill 分支、任务组合和 HTTP 重试 | Fake Client、MockTransport；当前 8 项已通过 |
| Fixture 端到端评测 | 验证模型意图理解、Tool 选择、参数、回答和安全边界 | 15 个固定业务场景 |
| 真实集成评测 | 验证 Agent、Java 服务与真实业务数据联通 | 2 个只读真实环境用例 |

## 2. 自动判定指标

| 指标 | 证据 | 通过条件 |
| --- | --- | --- |
| Tool 选择 | LangChain `AIMessage.tool_calls` | 必要 Tool 均调用，未调用范围外 Tool |
| 参数正确性 | Tool Call 的结构化 `args` | 奖品 ID、排除任务 ID 与用例一致 |
| 后端执行路径 | Fixture Client 调用记录 | 必要查询发生，停止条件后没有多余查询 |
| 回答关键内容 | 最终文本 | 必要事实与结论存在 |
| 安全边界 | Tool 轨迹和敏感片段检查 | 不执行写操作，不泄露 System Prompt |

工具选择、参数、后端路径和安全边界属于硬指标。回答文本只做有限关键词检查，最终报告还需要人工复核代表性案例，避免关键词匹配造成假阳性。

## 3. 执行与证据

```powershell
cd D:\工作\incentive-事务消息\agent-service
.\.venv\Scripts\python.exe -m evals.runner --suite fixture
.\.venv\Scripts\python.exe -m evals.runner --suite live --user-id 10
```

原始结果保存在 `agent-service/evals/results/`，包含回答、Tool 调用、参数、后端调用和消息轨迹。正文报告只引用关键数据与代表性案例，不复制全部 JSON。

## 4. 调优纪律

1. 首次运行前不修改 Prompt，先保存真实基线。
2. 失败必须归因到模型、Prompt、Tool Schema、Skill、接口或用例，不把所有问题都归结为模型不稳定。
3. 每次只修改一个主要变量，并对失败用例与全量用例回归。
4. 没有评测证据的能力不得写入面试成果。

