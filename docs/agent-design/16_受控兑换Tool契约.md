# 受控兑换 Tool 契约

> 这份契约把模型、Python Agent 服务和 Java 旧兑换链路之间的责任固定下来。后续代码可以调整类名，但不能绕过身份绑定、一次性确认、禁止盲目重试和稳定结果码这四条边界。

## 1. 统一返回结构

继续使用现有 `ToolEnvelope`：

```json
{
  "success": true,
  "code": "EXCHANGE_CONFIRMATION_REQUIRED",
  "data": {},
  "message": "请确认是否兑换",
  "retryable": false
}
```

`success` 表示工具是否按契约完成，不等于奖品最终兑换成功。Agent 必须优先按 `code` 分支，不能解析自由文本猜测状态。

## 2. `prepare_exchange`

这是准备动作，不修改积分、库存和订单。

### 输入

```json
{
  "award_id": 6
}
```

- `award_id`：正整数，由用户明确指定或通过奖品列表唯一解析。
- `user_id`、`session_id`、`request_id`：由运行时注入，不进入模型参数 Schema。

### 执行步骤

1. 调用现有资格查询，读取实时积分、奖品和资格原因码。
2. 资格不通过时直接返回原因，不生成凭证。
3. 资格通过时，使本会话旧的待确认凭证失效。
4. 创建一次性 `confirmation_id`，绑定用户、会话和奖品。
5. 返回兑换摘要和过期时间，等待用户确认。

### 成功数据

```json
{
  "confirmationId": "opaque-random-token",
  "status": "AWAITING_CONFIRMATION",
  "awardId": 6,
  "awardName": "机械键盘",
  "currentPoints": 3200,
  "requiredPoints": 1800,
  "remainingPoints": 1400,
  "expiresAt": "2026-08-20T21:30:00+08:00"
}
```

主要结果码：

| code | 含义 | 是否生成凭证 |
| --- | --- | --- |
| `EXCHANGE_CONFIRMATION_REQUIRED` | 当前满足条件，等待明确确认 | 是 |
| `INSUFFICIENT_POINTS` | 积分不足 | 否 |
| `OUT_OF_STOCK` | 库存不足 | 否 |
| `AWARD_NOT_STARTED` | 活动未开始 | 否 |
| `AWARD_EXPIRED` | 活动已结束 | 否 |
| `EXCHANGE_PROCESSING` | 已有请求处理中 | 否 |
| `ALREADY_REDEEMED` | 已兑换 | 否 |
| `QUERY_FAILED` | 资格查询失败 | 否 |

## 3. `confirm_exchange`

这是唯一允许触发真实兑换的高风险写 Tool。

### 输入

```json
{
  "confirmation_id": "opaque-random-token"
}
```

不接收 `award_id` 和 `user_id`。这两个值必须来自服务端确认记录，避免模型在确认时替换奖品或用户。

### 执行步骤

1. 查询凭证并校验用户、会话、状态和有效期。
2. 原子地将状态从 `PREPARED` 改为 `EXECUTING`；失败则不调用 Java。
3. 调用 Java Agent 写入适配接口，并透传 `X-Request-ID` 与 `Idempotency-Key`。
4. 将 Java 稳定结果码映射为 `PROCESSING`、`REJECTED` 或 `UNKNOWN`。
5. 保存审计摘要并返回，不轮询最终兑换结果。

### 主要结果码

| code | success | 含义 | 后续动作 |
| --- | --- | --- | --- |
| `CONFIRMATION_NOT_FOUND` | false | 凭证不存在或不属于当前用户/会话 | 重新准备 |
| `CONFIRMATION_EXPIRED` | false | 凭证已过期 | 重新准备并展示最新条件 |
| `CONFIRMATION_ALREADY_USED` | false | 凭证已被消费 | 不再次调用兑换接口 |
| `EXCHANGE_REJECTED` | false | Java 明确返回业务拒绝 | 展示稳定原因，不自动重试 |
| `ALREADY_REDEEMED` | false | 已经兑换成功 | 不重复提交 |
| `EXCHANGE_PROCESSING` | true | 旧链路返回正在处理；可能是本次刚受理，也可能是此前已在处理 | 不重复提交，转订单页面 |
| `SUBMISSION_UNKNOWN` | false | 超时、连接中断或响应格式异常 | 禁止自动重试，提示先核对订单 |

`SUBMISSION_UNKNOWN` 的 `retryable` 必须为 `false`。这里的 `false` 表示 Agent 不应自动重放写请求，不代表用户永远不能在人工核对后再次操作。

## 4. Java 写入适配接口

建议新增专供 Agent 服务调用的明确写接口，而不是让 Python 直接调用现有 GET：

```http
POST /agent/commands/users/{userId}/awards/{awardId}/exchange
X-Request-ID: req-...
Idempotency-Key: confirmation-id
```

第一版本地联调仍可从路径接收 `userId`，但接口内部必须把它视为服务端身份上下文；正式接入登录态后，应忽略模型可控的身份参数。

适配层负责调用现有 `UserAwardService.exchange(userId, awardId)`，并把旧返回码转换为稳定 `AgentToolResponse`：

| 旧返回码 | Agent code | 说明 |
| --- | --- | --- |
| `502 Query_Later` | `EXCHANGE_PROCESSING` | 当前源码无法区分本次刚受理和此前已在处理，不能说最终成功 |
| `505 AWARD_REDEEMED` | `ALREADY_REDEEMED` | 不再次提交 |
| `506 INSUFFICIENT_CURRENCY` | `EXCHANGE_REJECTED` | 确认时积分条件已经变化 |
| `508 AWARD_EXPIRE` | `EXCHANGE_REJECTED` | 活动已结束 |
| `510 AWARD_NOT_STARTED` | `EXCHANGE_REJECTED` | 活动尚未开始 |
| `507 TRANSACTION_SEND_FAILED` | `EXCHANGE_REJECTED` | Java 明确表示发送失败，但 Agent 不自动重试 |
| `501/503/509` | `EXCHANGE_REJECTED` | 参数或当前业务条件拒绝，保留可展示说明 |

`Idempotency-Key` 只有在接收方执行原子占用或持久化去重时才是真正的幂等机制。如果第一版 Java 适配层尚未实现命令级去重，它只能作为审计关联字段；此时防重复主要依赖确认存储的原子消费，绝不能据此开放 POST 自动重试。多实例或跨进程恢复前，应补充 Java/共享存储侧的命令幂等记录。

## 5. 重试边界

| 场景 | Tool 层 | Skill 层 | Agent/模型层 |
| --- | --- | --- | --- |
| 准备阶段 GET 超时、`408/429/5xx` | 沿用现有限次退避 | 不叠加重试 | 不重复调用 |
| 确认阶段参数或凭证错误 | 不重试 | 不重试 | 引导重新准备 |
| Java 明确返回业务拒绝 | 不重试 | 不重试 | 解释原因 |
| POST 超时、连接中断、`5xx` | 不自动重试 | 标记 `UNKNOWN` | 提示先核对订单 |
| 重复确认 | 不调用 Java | 返回已使用 | 不再次调用 |

旧链路虽然存在用户与奖品维度的幂等保护，但当前事务回查和幂等模型不包含 Agent 请求 ID，因此不能仅凭“理论上幂等”就允许自动重试未知状态的 POST。

## 6. 确认存储的原子约束

接口至少需要以下操作：

```text
create(user, session, award, ttl) -> confirmation_id
claim(confirmation_id, user, session, expected=PREPARED) -> bool
finish(confirmation_id, EXECUTING -> ACCEPTED|REJECTED|UNKNOWN)
invalidate_pending(user, session)
```

`claim` 必须以比较并设置的方式完成，不能先读取状态再普通赋值。进程内实现使用同一把锁保护检查与更新；Redis 实现使用 Lua 或事务条件更新。

## 7. 审计字段

每次状态变化至少记录：

- `request_id`、`confirmation_id`、`user_id`、`session_id`、`award_id`
- 旧状态、新状态、事件时间
- Tool 名称、Java 稳定结果码、耗时和异常类型

日志不记录完整用户消息、API Key、数据库连接信息和完整业务响应。`confirmation_id` 在普通日志中可只保留哈希或前后缀，避免它成为可复制的授权凭据。
