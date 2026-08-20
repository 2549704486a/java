# 积分规划与奖品兑换顾问

这是积分激励项目的第一版最小 Agent。它只读取 Java 服务提供的业务事实，帮助用户判断奖品是否可兑换，并在积分不足时生成任务方案。

## 1. 当前能力

- 通过 LangChain `create_agent` 运行 Function Calling 循环。
- 使用 5 个基础查询 Tool 和 2 个只读组合 Skill。
- `plan_points_for_award` 使用确定性代码计算积分缺口和任务组合。
- `recommend_awards` 使用确定性代码过滤并排序当前真正可兑换的奖品。
- 启动时发现并校验 `skills/*/SKILL.md`，Tool 描述、Skill 版本和哈希来自声明文件。
- 提供 FastAPI HTTP 接口，支持请求校验、请求 ID、错误脱敏和有界 Agent 缓存。
- Tool 层只对 GET 请求的瞬时网络错误做有限重试。
- 不直连 MySQL、Redis、RocketMQ，不调用兑换和任务写接口。

课程讲义中的 `langgraph.prebuilt.create_react_agent` 在当前版本已由 `langchain.agents.create_agent` 取代，二者承担相同的“模型决定工具 -> 执行工具 -> 返回结果 -> 继续推理”循环。

## 2. 环境准备

要求 Python 3.11。先启动 Java 服务，默认地址为 `http://127.0.0.1:8088`。

```powershell
cd D:\工作\incentive-事务消息\agent-service
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

自然语言 Agent 需要在 `.env` 中填写 OpenAI 兼容模型的 `LLM_API_KEY`、`LLM_BASE_URL` 和 `LLM_MODEL`。不要提交真实密钥。

### API Key 配置

先创建只在本机使用的配置文件：

```powershell
Copy-Item .env.example .env
notepad .env
```

使用 OpenAI 官方接口时：

```dotenv
LLM_API_KEY=你的API_KEY
LLM_BASE_URL=
LLM_MODEL=你账户可用且支持工具调用的模型名
```

使用其他 OpenAI 兼容服务时：

```dotenv
LLM_API_KEY=服务商提供的API_KEY
LLM_BASE_URL=服务商提供的兼容接口地址
LLM_MODEL=服务商提供的模型名
```

`.env` 已被项目 `.gitignore` 忽略。不要把真实 Key 发到聊天、提交到 Git 或写进截图；如果曾经泄露，应立即在服务商控制台撤销并重新创建。

## 3. 先验证业务 Skill

这一步不调用大模型，只验证 Java 接口和确定性积分计算：

```powershell
.\.venv\Scripts\python.exe -m app.main --user-id 10 --plan-award-id 6
.\.venv\Scripts\python.exe -m app.main --user-id 10 --recommend-awards 3
```

Agent 启动时只把 Skill 的名称、描述、触发条件和版本通过 Tool 元数据提供给模型。调用 `plan_points_for_award` 时，运行时激活完整 Skill 定义并记录版本与 SHA-256；积分计算仍由 `app/skills/points_plan.py` 的确定性代码完成，不让模型按说明文字自行计算。

## 4. 运行 Agent

单次提问：

```powershell
.\.venv\Scripts\python.exe -m app.main --user-id 10 --message "我想兑换 6 号奖品，积分不够该做哪些任务？"
```

交互模式：

```powershell
.\.venv\Scripts\python.exe -m app.main --user-id 10
```

## 5. 运行 HTTP 服务

单独启动：

```powershell
.\.venv\Scripts\python.exe -m app.server
```

也可以在项目根目录使用一键脚本，它会在 Java 服务就绪后启动 Agent：

```powershell
.\start-local.ps1
```

如果这次不需要 Agent，可以添加 `-SkipAgent`。默认监听 `127.0.0.1:8090`，接口文档位于 `http://127.0.0.1:8090/docs`。

健康检查：

```powershell
Invoke-RestMethod http://127.0.0.1:8090/health
```

调用 Agent：

```powershell
$json = @{
    user_id = 10
    session_id = 'local-session-001'
    message = '我想兑换 6 号奖品，积分不够该做哪些任务？'
} | ConvertTo-Json
$body = [Text.Encoding]::UTF8.GetBytes($json)

Invoke-RestMethod `
    -Method Post `
    -Uri http://127.0.0.1:8090/v1/chat `
    -ContentType 'application/json; charset=utf-8' `
    -Headers @{ 'X-Request-ID' = 'local-demo-001' } `
    -Body $body
```

响应包含 `request_id`、`session_id`、`user_id`、`answer` 和服务端总耗时 `elapsed_ms`。首次不传 `session_id` 时服务会生成并返回；后续请求携带同一个 `session_id` 即可延续对话。

短期记忆只保存在当前进程内，并按 `user_id + session_id` 隔离。服务重启或会话被 LRU 淘汰后，历史消息不会保留。

## 6. 测试

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

离线测试不需要 Java 服务和模型密钥，覆盖 Skill 发现与声明校验、运行时激活、资格分支、任务选择、任务排除、积分不足和 Tool 瞬时错误重试。

## 7. Agent 评测

固定 Fixture 用例不依赖真实业务状态，真实集成用例需要 Java 服务运行：

```powershell
.\.venv\Scripts\python.exe -m evals.runner --suite fixture
.\.venv\Scripts\python.exe -m evals.runner --suite live --user-id 10
.\.venv\Scripts\python.exe -m evals.multiturn_runner
```

结果保存在 `evals/results/`，包含最终回答、模型声明调用、实际 Tool 执行轨迹、参数、结果码、Tool 耗时、后端路径和消息轨迹。汇总区会按 Tool 统计调用次数、执行失败数、平均耗时和最大耗时。修改评分规则后可以对同一模型输出离线重评，避免反复调用模型碰结果：

```powershell
.\.venv\Scripts\python.exe -m evals.rescore --input evals\results\原结果.json --output evals\results\重评结果.json
```

## 8. 日志与耗时

默认日志文件：

```text
agent-service/logs/agent-service.log
```

日志会记录 HTTP 请求 ID、用户 ID、请求总耗时，每次 Java 业务接口的路径、HTTP 状态、业务码、重试次数和耗时，以及组合 Skill 的名称、版本、定义哈希和总耗时。

每次 Agent 调用还会输出一条 `agent_tool_trace` 结构化日志，以 `request_id` 关联本次实际执行的 Tool/Skill，记录参数、完成状态、业务结果码和耗时。轨迹不记录 API Key、用户问题正文和完整业务响应。

Spring Boot 请求日志由一键启动脚本保存到：

```text
.local-runtime/logs/incentive-app.out.log
```
