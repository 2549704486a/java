# 受控兑换 Skill 实现

> 这一阶段把受控兑换从设计变成可执行代码。难点不在调用一次 POST，而在于把“用户真的确认过这一次兑换”和“写请求最多执行一次”落实为服务端状态，而不是依赖模型记住一句话。

## 1. 完整调用链

```text
用户提出兑换
  -> prepare_exchange
  -> Java 实时资格与奖品查询
  -> ConfirmationStore 创建 PREPARED 凭证
  -> Agent 展示奖品、积分消耗和有效期
  -> 用户在同一会话明确确认
  -> confirm_exchange 原子 claim：PREPARED -> EXECUTING
  -> POST /agent/commands/.../exchange
  -> UserAwardService.exchange 执行旧事务消息链路
  -> PROCESSING / REJECTED / UNKNOWN
```

准备和确认被拆开后，模型只负责理解意图和选择 Tool；用户、会话、奖品、过期时间和凭证状态由确定性代码校验。

## 2. 关键实现

| 位置 | 作用 |
| --- | --- |
| `app/confirmation_store.py` | 使用锁保护凭证创建、过期、取消和原子占用 |
| `app/execution_context.py` | 使用 `ContextVar` 将运行时 `thread_id` 注入 Tool，不允许模型填写会话 |
| `app/skills/controlled_exchange.py` | 编排资格、摘要、确认状态机与写接口结果 |
| `app/api_client.py` | 单次发送兑换 POST；超时、断连、5xx 和格式异常均不重试 |
| `app/tools.py` | 暴露 prepare、confirm、cancel 三个 Tool，并隐藏轨迹中的完整凭证 |
| `AgentCommandController.java` | 将稳定 Agent POST 契约映射到现有 `UserAwardService.exchange` |

`Idempotency-Key` 当前用于关联请求。第一版真正防止 Agent 重复提交的是 Python 确认存储的原子 `claim`；多实例部署时必须使用 Redis Lua 或数据库条件更新，并补接收端持久化幂等。

## 3. 状态语义

- `EXCHANGE_CONFIRMATION_REQUIRED`：只完成准备，尚未写入。
- `EXCHANGE_PROCESSING`：旧事务消息链路已进入处理流程，不代表最终兑换成功。
- `EXCHANGE_REJECTED` / `ALREADY_REDEEMED`：Java 给出明确业务结果，不自动重试。
- `SUBMISSION_UNKNOWN`：无法判断 POST 是否到达 Java，先核对订单，禁止盲目重放。

会话被 LRU 淘汰或用户主动取消时，尚未使用的凭证同步失效。普通日志记录状态变化和业务码，但不记录完整确认凭证。

## 4. 验证证据

- Python 离线测试 `42/42` 通过，覆盖 TTL、身份和会话绑定、会话淘汰撤销、跨轮确认、重复/并发确认、未知结果及轨迹脱敏。
- Java `AgentCommandControllerTest` 与 `AgentQueryServiceTest` 定向测试通过。
- React TypeScript 生产构建通过。
- 本地重新部署后，Agent 健康检查发现 3 个 Skill，待确认数量为 0。
- 使用不存在的用户进行安全 POST 冒烟，接口真实返回 `EXCHANGE_REJECTED`，未进入事务消息发送。
- 自然语言冒烟中，“想兑换”只生成确认摘要，“取消兑换”使待确认数量从 1 回到 0；要求“跳过确认直接提交”时也只有 prepare 轨迹，没有写接口调用。

## 5. 当前边界

- 只接入旧事务消息链路，没有恢复或引入 Redis 预扣新链路。
- 凭证是单进程内存状态，服务重启即失效，符合安全默认但不支持多实例共享。
- 本地演示身份仍由前端用户 ID 提供，生产系统必须从登录态或网关注入可信身份。
- 本轮完成确定性代码安全测试，设计文档中的模型意图识别用例仍应作为后续 Agent 回归集持续执行。
