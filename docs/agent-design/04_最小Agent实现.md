# 最小 Agent 实现说明

> 第一版只解决一个多步问题：用户指定目标奖品后，查询动态业务事实，并生成可信的积分规划。它不是兑换接口的自然语言包装，也不代替页面查询订单结果。

## 1. 代码位置

- Python Agent：`agent-service/`
- Java 只读接口：`incentive/src/main/java/com/budou/incentive/controller/AgentQueryController.java`
- 组合 Skill：`agent-service/app/skills/points_plan.py`
- Skill 声明：`agent-service/skills/points-planning/SKILL.md`
- System Prompt：`agent-service/app/prompt.py`
- Function Calling Tool：`agent-service/app/tools.py`

## 2. 最小调用链

```text
用户自然语言
  -> System Prompt 限定职责和只读边界
  -> LangChain Agent 判断是否调用工具
  -> Tool 通过 HTTP 调用 Java /agent/query/**
  -> plan_points_for_award 编排资格、奖品和任务查询
  -> 确定性代码计算任务组合与积分缺口
  -> 模型依据结构化结果生成自然语言回复
```

模型不直接访问数据库，也不负责关键积分运算。即使模型不可用，也可以通过 `--plan-award-id` 单独验证业务 Skill。

## 3. 课程技术对应

- 第二讲 Prompt：明确角色、能力、工具规则、安全边界和输出方式。
- 第三讲 Function Calling：工具使用明确的名称、描述和 Pydantic 参数 Schema；模型只声明调用意图，代码执行工具。
- 第四讲 LangChain：采用当前 `langchain.agents.create_agent` 构建工具调用循环。
- 第十讲 Skill：把资格判断、任务查询、确定性计算、停止条件和重试边界封装为积分规划 Skill。

## 4. 当前边界

- 用户身份由启动参数绑定，后续接入 Web 时应改由认证上下文注入。
- 第一版无长期记忆、RAG、MCP 和多 Agent。
- 第一版不开放兑换、任务完成和领奖等写操作。
- 不读取或依赖历史压测结果与压测文档。

## 5. 验证方式

```powershell
cd D:\工作\incentive-事务消息\agent-service
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m app.main --user-id 10 --plan-award-id 6
```

