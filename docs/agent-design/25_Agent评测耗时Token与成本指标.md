# Agent 评测耗时、Token 与成本指标

> 只看最终通过率无法回答“为什么慢”和“跑一次要花多少钱”。这一轮把 Agent 端到端耗时、模型调用耗时、Tool 耗时和 Token 成本拆开统计，让质量、性能和费用能够在同一份评测结果中对照。

## 1. 三类耗时不能混为一谈

| 指标 | 计时范围 | 可以回答的问题 |
| --- | --- | --- |
| Agent 端到端耗时 | `agent.invoke` 开始到最终消息返回 | 用户等待了多久 |
| 模型调用耗时 | 每次 LangChain 模型回调开始到结束 | 时间主要是否消耗在模型调用 |
| Tool 执行耗时 | Tool 实际执行开始到结束 | 哪个业务查询或 Skill 较慢 |

ReAct Agent 可能多次调用模型。例如第一次模型决定查询积分，Tool 返回后，第二次模型再组织答案。因此一次 Agent 请求可能对应多次模型调用；`model_metrics.calls` 不能默认等于请求数。

模型调用耗时是 Agent 客户端观测到的时间，包含访问模型服务的网络、服务端排队和生成时间。它不是模型供应商内部的纯推理耗时，除非供应商额外提供了服务端指标。

本轮同时修复了一个统计缺陷：原汇总函数复用了 `elapsed_values` 变量，存在把最后一个 Tool 的耗时当成 Agent 整体耗时的风险。现在整体和 Tool 分别使用独立变量，并有回归测试验证。

## 2. Token 指标

Runner 从每条 AI 消息的 `usage_metadata` 汇总：

- `input_tokens`：发送给模型的输入 Token 总数。
- `output_tokens`：模型生成的输出 Token 总数。
- `total_tokens`：输入与输出 Token 总数。
- `average_tokens_per_attempt`：每次用例尝试平均消耗的 Token。
- `usage_coverage_rate`：返回 Token 统计的尝试数占比。

`usage_coverage_rate` 很重要。某些 OpenAI 兼容服务不返回 `usage_metadata`，此时 Token 为 0 不代表没有消耗，而是没有观测数据，不能据此宣称零成本。

## 3. 成本如何计算

模型价格不写死在代码里，因为模型版本、服务商和计费标准都可能变化。运行评测时显式提供当前合同或服务商页面中的单价：

```powershell
$inputPrice = [double](Read-Host "每百万输入 Token 的美元单价")
$outputPrice = [double](Read-Host "每百万输出 Token 的美元单价")
.\.venv\Scripts\python.exe -m evals.runner `
  --dataset tuning `
  --suite fixture `
  --repeat 3 `
  --input-cost-per-million $inputPrice `
  --output-cost-per-million $outputPrice
```

计算公式为：

```text
输入成本 = 输入 Token / 1,000,000 × 输入单价
输出成本 = 输出 Token / 1,000,000 × 输出单价
总成本   = 输入成本 + 输出成本
```

两个单价必须同时配置。没有配置时，评测仍会统计 Token，但 `estimated_cost.available=false`，不会用 0 元掩盖未知价格。结果使用 `estimated` 命名，是因为本地统计可能与服务商账单的缓存折扣、批处理折扣和计费取整不同。

历史结果若保存了 Token，可以通过 `rescore.py` 传入相同价格离线重算成本，不需要再次调用模型。历史结果没有模型回调轨迹时，模型耗时覆盖率会是 0，不能从端到端耗时反推出精确模型耗时。

## 4. 结果字段

汇总 JSON 新增两个区域：

```json
{
  "token_metrics": {
    "usage_coverage_rate": 1.0,
    "input_tokens": 0,
    "output_tokens": 0,
    "total_tokens": 0,
    "estimated_cost": {
      "available": false,
      "reason": "pricing_not_configured"
    }
  },
  "model_metrics": {
    "calls": 0,
    "failures": 0,
    "average_call_elapsed_ms": 0,
    "p95_call_elapsed_ms": 0,
    "average_calls_per_attempt": 0
  }
}
```

示例中的 0 只是字段结构，不是本项目的新评测结论。本轮没有调用真实模型，避免为了验证统计代码产生费用；指标计算由单元测试验证。

## 5. 当前边界

- 端到端耗时不等于模型耗时，二者必须分别汇报。
- 模型耗时包含网络和供应商排队，不能包装为纯推理耗时。
- 本地成本是按显式单价计算的估算值，最终账单以服务商为准。
- Prompt 缓存 Token、推理 Token等细分类别尚未统一，因为不同兼容服务返回结构不一致；后续有真实需求再扩展。
