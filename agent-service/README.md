# 积分规划与奖品兑换顾问

这是积分激励项目的第一版最小 Agent。它只读取 Java 服务提供的业务事实，帮助用户判断奖品是否可兑换，并在积分不足时生成任务方案。

## 1. 当前能力

- 通过 LangChain `create_agent` 运行 Function Calling 循环。
- 使用 5 个只读查询 Tool 和 1 个组合 Skill。
- `plan_points_for_award` 使用确定性代码计算积分缺口和任务组合。
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
```

## 4. 运行 Agent

单次提问：

```powershell
.\.venv\Scripts\python.exe -m app.main --user-id 10 --message "我想兑换 6 号奖品，积分不够该做哪些任务？"
```

交互模式：

```powershell
.\.venv\Scripts\python.exe -m app.main --user-id 10
```

## 5. 测试

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

离线测试不需要 Java 服务和模型密钥，覆盖资格分支、任务选择、任务排除、积分不足和 Tool 瞬时错误重试。

## 6. Agent 评测

固定 Fixture 用例不依赖真实业务状态，真实集成用例需要 Java 服务运行：

```powershell
.\.venv\Scripts\python.exe -m evals.runner --suite fixture
.\.venv\Scripts\python.exe -m evals.runner --suite live --user-id 10
```

结果保存在 `evals/results/`，包含最终回答、Tool 调用、参数、后端路径和消息轨迹。修改评分规则后可以对同一模型输出离线重评，避免反复调用模型碰结果：

```powershell
.\.venv\Scripts\python.exe -m evals.rescore --input evals\results\原结果.json --output evals\results\重评结果.json
```

## 7. 日志与耗时

默认日志文件：

```text
agent-service/logs/agent-service.log
```

日志会记录每次 Java 业务接口的路径、HTTP 状态、业务码、重试次数和耗时，以及积分规划 Skill 的总耗时，不记录 API Key 和完整业务响应。

Spring Boot 请求日志由一键启动脚本保存到：

```text
.local-runtime/logs/incentive-app.out.log
```
