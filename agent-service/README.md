# 积分规划与奖品兑换顾问

这是积分激励项目的业务 Agent。它读取 Java 服务提供的实时事实，帮助用户判断兑换条件、生成任务方案，并通过一次性确认凭证受控地调用旧事务消息兑换链路。

## 1. 当前能力

- 通过 LangChain `create_agent` 运行 Function Calling 循环。
- 使用 5 个基础查询 Tool、2 个只读组合 Skill、1 个受控兑换 Skill 和 1 个长期记忆 Skill。
- `plan_points_for_award` 使用确定性代码计算积分缺口和任务组合。
- `recommend_awards` 使用确定性代码过滤并排序当前真正可兑换的奖品。
- 启动时发现并校验 `skills/*/SKILL.md`，Tool 描述、Skill 版本和哈希来自声明文件。
- 提供 FastAPI HTTP 接口，支持请求校验、请求 ID、错误脱敏和有界 Agent 缓存。
- 使用空闲 TTL 回收会话，并在每次模型调用前按完整轮次和估算 token 裁剪可见上下文；裁剪指标与模型实际 token 写入日志。
- 使用签名 JWT 验证用户身份，查询、会话和兑换不接受浏览器自行指定用户 ID。
- 建立受控 RAG 知识源目录，已实现文档切分、本地 Chroma 索引、在线只读检索、来源引用和新鲜度门禁。
- Tool 层只对 GET 请求的瞬时网络错误做有限重试；兑换 POST 绝不自动重试。
- 兑换必须经过“准备摘要 -> 用户明确确认 -> 服务端确定性路由 -> 原子消费一次性凭证”，确认凭证不进入模型上下文，受理后仍由旧事务消息链路异步完成。
- 用户直接明确表达的稳定兑换目标和偏好经校验后直接写入，支持跨会话读取、修改、遗忘和目标过期标记；临时需求与模型推断不写入。
- 不直连业务 MySQL 和 RocketMQ；只使用独立 Redis Key 前缀保存 Agent 自己的确认授权与长期记忆，不直接修改积分、库存和任务状态。

课程讲义中的 `langgraph.prebuilt.create_react_agent` 在当前版本已由 `langchain.agents.create_agent` 取代，二者承担相同的“模型决定工具 -> 执行工具 -> 返回结果 -> 继续推理”循环。

## 2. 环境准备

要求 Python 3.11。先启动 Redis 和 Java 服务，默认地址分别为 `127.0.0.1:6379` 和 `http://127.0.0.1:8088`。

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

同时配置本地 JWT 签名密钥：

```dotenv
AGENT_AUTH_SECRET=至少32字符的本地随机密钥
AGENT_AUTH_ISSUER=incentive-agent
AGENT_AUTH_AUDIENCE=incentive-agent-web
AGENT_ACCESS_TOKEN_TTL_SECONDS=3600
AGENT_SESSION_TTL_SECONDS=3600
AGENT_CONTEXT_MAX_TOKENS=6000
AGENT_CONTEXT_MAX_TURNS=12
GROWTH_MEMORY_STORE=redis
GROWTH_MEMORY_REDIS_URL=redis://127.0.0.1:6379/0
GROWTH_MEMORY_REDIS_PREFIX=agent:growth:memory
```

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

受控兑换示例：先说“我想兑换 6 号奖品”，Agent 展示奖品和积分摘要后，再在同一会话明确回复“确认兑换”。`EXCHANGE_PROCESSING` 只表示已进入旧链路处理流程，最终结果需要到订单页面查看；遇到 `SUBMISSION_UNKNOWN` 时先核对订单，不要立即重复提交。

长期记忆示例：说“我喜欢数码类奖品”或“请记住，我想在 2026-09-01 前兑换 6 号奖品”，Agent 会把直接、稳定的陈述校验后保存，并明确告知结果。之后的新会话可以询问“你记得我喜欢什么奖品吗”或“我的兑换目标是什么”。“这次想看数码类奖品”只作为本轮条件，不会保存；说“忘掉我的兑换目标”时会按明确范围直接删除。

## 5. 运行 HTTP 服务与前端

单独启动：

```powershell
.\.venv\Scripts\python.exe -m app.server
```

也可以在项目根目录使用一键脚本，它会在 Java 服务就绪后启动 Agent：

```powershell
.\start-local.ps1
```

如果这次不需要 Agent，可以添加 `-SkipAgent`。脚本会自动安装并构建 `web-ui`，默认监听 `127.0.0.1:8090`：

- 奖品中心与 Agent 对话：`http://127.0.0.1:8090/`
- 接口文档：`http://127.0.0.1:8090/docs`
- 当前身份：`GET /v1/me`
- 聚合首屏数据：`GET /v1/dashboard`

使用 `-SkipWeb` 可以跳过前端构建。前端独立开发和构建方式见 `web-ui/README.md`。

健康检查：

```powershell
Invoke-RestMethod http://127.0.0.1:8090/health
```

调用 Agent：

```powershell
$token = .\.venv\Scripts\python.exe -m app.auth --user-id 10
$json = @{
    session_id = 'local-session-001'
    message = '我想兑换 6 号奖品，积分不够该做哪些任务？'
} | ConvertTo-Json
$body = [Text.Encoding]::UTF8.GetBytes($json)

Invoke-RestMethod `
    -Method Post `
    -Uri http://127.0.0.1:8090/v1/chat `
    -ContentType 'application/json; charset=utf-8' `
    -Headers @{
        'X-Request-ID' = 'local-demo-001'
        'Authorization' = "Bearer $token"
    } `
    -Body $body
```

响应包含 `request_id`、`session_id`、`user_id`、`answer`、服务端总耗时 `elapsed_ms`，以及安全的待确认兑换摘要。首次不传 `session_id` 时服务会生成并返回；后续请求携带同一个 `session_id` 即可延续对话。

本地签发命令使用 `.env` 中的 JWT 密钥。生产环境应由正式登录系统签发身份，不能把签名密钥交给浏览器，也不能提供公开的“输入用户 ID 换 Token”接口。

短期记忆只保存在当前进程内，并按 `user_id + session_id` 隔离。服务重启或会话被 LRU 淘汰后，历史消息不会保留。

## 6. 测试

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

离线测试不需要 Java 服务和模型密钥，覆盖 Skill 发现、规划与推荐分支、一次性凭证 TTL、用户/会话绑定、重复与并发确认、POST 禁止重试、轨迹脱敏和 HTTP 契约。

Redis 多实例原子消费属于集成测试，需先启动 Redis 后显式开启：

```powershell
$env:RUN_REDIS_INTEGRATION_TESTS = '1'
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
Remove-Item Env:RUN_REDIS_INTEGRATION_TESTS
```

## 7. Agent 评测

固定 Fixture 用例不依赖真实业务状态，真实集成用例需要 Java 服务运行：

```powershell
.\.venv\Scripts\python.exe -m evals.runner --suite fixture
.\.venv\Scripts\python.exe -m evals.runner --suite live --user-id 10
.\.venv\Scripts\python.exe -m evals.multiturn_runner
```

公开调优集用于日常回归；冻结盲测集只在阶段验收时运行。关键用例应重复至少 3 次，汇总会输出逐用例通过率、稳定/波动状态、耗时 P95 和标准差：

```powershell
.\.venv\Scripts\python.exe -m evals.runner --dataset tuning --suite fixture --repeat 3
.\.venv\Scripts\python.exe -m evals.runner --dataset blind --suite fixture --repeat 3
```

盲测结果默认脱敏，不保存问题、回答、期望内容和完整轨迹，不能用于离线重评分。具体治理规则见 `docs/agent-design/24_评测集隔离与重复试验.md`。

结果保存在 `evals/results/`，包含最终回答、模型声明调用、实际 Tool 执行轨迹、参数、结果码、Tool 耗时、后端路径和消息轨迹。汇总区会分别统计 Agent 端到端耗时、模型调用耗时、Tool 耗时和 Token；模型价格不会硬编码，只有同时传入当前输入与输出单价时才估算美元成本：

```powershell
$inputPrice = [double](Read-Host "每百万输入 Token 的美元单价")
$outputPrice = [double](Read-Host "每百万输出 Token 的美元单价")
.\.venv\Scripts\python.exe -m evals.runner `
  --suite fixture `
  --input-cost-per-million $inputPrice `
  --output-cost-per-million $outputPrice
```

详细口径见 `docs/agent-design/25_Agent评测耗时Token与成本指标.md`。修改评分规则或价格后，可以对保留了完整回答和 Token 的同一模型输出离线重评，避免反复调用模型碰结果：

```powershell
.\.venv\Scripts\python.exe -m evals.rescore --input evals\results\原结果.json --output evals\results\重评结果.json
```

## 8. 构建 RAG 知识索引

当前已完成知识源治理、文档切分和本地向量索引构建，还没有把 RAG 检索接入 Agent。新增或修改 `knowledge/documents/` 后，先审核动态事实边界并同步文档版本与目录版本，再执行目录校验和切分检查：

```powershell
.\.venv\Scripts\python.exe -m app.knowledge_catalog
.\.venv\Scripts\python.exe -m app.knowledge_index inspect-chunks
```

配置 `RAG_EMBEDDING_API_KEY`、`RAG_EMBEDDING_BASE_URL` 和 `RAG_EMBEDDING_MODEL` 后，可以重建本地持久化索引：

```powershell
.\.venv\Scripts\python.exe -m app.knowledge_index build
```

建库成功后再设置 `RAG_ENABLED=true` 并重启 Agent。Runtime 会校验索引非空，然后按需注册只读 `search_business_knowledge` Tool；低相关查询返回无答案，不会让模型猜测规则。聊天兼容接口不一定提供 Embedding，请以服务商实际模型能力为准。

校验器会检查清单契约、重复 ID、目录穿越、YAML Front Matter、固定章节和项目内来源；索引器会保留章节与来源元数据，并通过临时集合保护当前正式索引。详细设计见 `docs/agent-design/26_RAG知识源治理与Tool边界.md`、`27_RAG文档切分与本地向量索引.md` 和 `28_RAG只读检索与来源引用.md`。

## 9. 日志与耗时

默认日志文件：

```text
agent-service/logs/agent-service.log
```

日志会记录 HTTP 请求 ID、用户 ID、请求总耗时，每次 Java 业务接口的路径、HTTP 状态、业务码、重试次数和耗时，以及组合 Skill 的名称、版本、定义哈希和总耗时。确认凭证不写入普通日志或 Tool 轨迹。

每次 Agent 调用还会输出一条 `agent_tool_trace` 结构化日志，以 `request_id` 关联本次实际执行的 Tool/Skill，记录参数、完成状态、业务结果码和耗时。轨迹不记录 API Key、用户问题正文和完整业务响应。

Spring Boot 请求日志由一键启动脚本保存到：

```text
.local-runtime/logs/incentive-app.out.log
```
