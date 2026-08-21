# 受控兑换 Skill 实现

> 这一阶段把“用户想兑换”与“用户确认执行”拆成两个回合。模型只负责理解兑换目标和生成摘要；真正的确认授权由服务端状态机判断，避免模型误调用写接口或泄露一次性凭证。

## 1. 完整调用链

```text
用户提出兑换
  -> 模型调用 prepare_exchange
  -> Java 实时查询资格与奖品
  -> ConfirmationStore 创建 PREPARED 记录
  -> 模型只看到不含凭证的业务摘要
  -> FastAPI 向页面返回 pending_exchange 安全摘要
  -> 用户在同一会话点击确认或明确回复“确认兑换”
  -> AgentRuntime 白名单识别确认意图，不再经过模型
  -> 服务端取出一次性凭证并原子 claim：PREPARED -> EXECUTING
  -> POST /agent/commands/users/{userId}/awards/{awardId}/exchange
  -> Java 复用旧事务消息链路
  -> PROCESSING / REJECTED / UNKNOWN
```

准备阶段允许模型调用 `prepare_exchange`，但 `confirmationId` 在 Tool 返回给模型前会被移除。确认阶段没有模型可调用的 `confirm_exchange` Tool，凭证只在服务端 `ConfirmationStore` 与确定性执行器之间流转。

## 2. 关键实现

| 位置 | 作用 |
| --- | --- |
| `app/confirmation_store.py` | 定义统一存储契约，并提供供单元测试使用的内存实现 |
| `app/redis_confirmation_store.py` | 使用 Redis 和 Lua 保存共享凭证并完成跨实例原子状态迁移 |
| `app/skills/controlled_exchange.py` | 编排准备、确认和取消；用保守短语白名单识别明确动作 |
| `app/runtime.py` | 有待确认记录时确定性路由确认或取消，不让模型猜测高风险授权 |
| `app/tools.py` | 向模型暴露 prepare/cancel，移除 prepare 结果中的一次性凭证 |
| `app/web.py` | 返回不含凭证的 `pending_exchange` 页面契约 |
| `web-ui/src/components/ChatPanel.tsx` | 展示结构化确认卡片与确认、取消按钮 |
| `app/api_client.py` | 单次发送兑换 POST；超时、断连、5xx 和格式异常均不自动重试 |
| `AgentCommandController.java` | 将稳定 Agent POST 契约映射到原有旧事务消息链路 |

`Idempotency-Key` 由确认凭证生成并随 POST 发送。Java 端会先写入 `agent_exchange_request` 占位，再调用旧链路；同键同参数会重放已持久化响应，同键异参会明确冲突，异常和过期执行会进入未知状态且不自动重放。Python 确认记录已迁移到 Redis，使用 Lua 保证多 Agent 实例之间最多只有一个实例能将凭证从 `PREPARED` 改为 `EXECUTING`。两层实现分别见 `21_Java兑换请求持久化幂等.md` 和 `22_Redis确认凭证共享存储.md`。

## 3. 状态语义

- `EXCHANGE_CONFIRMATION_REQUIRED`：只生成确认摘要，没有写业务数据。
- `EXCHANGE_PROCESSING`：旧事务消息链路已经受理，不代表最终兑换成功。
- `EXCHANGE_REJECTED` / `ALREADY_REDEEMED`：Java 给出明确拒绝结果，不自动重试。
- `SUBMISSION_UNKNOWN`：无法确定 POST 是否到达 Java，要求先查订单，禁止盲目重放。

会话被 LRU 淘汰、确认过期、用户改换奖品或主动取消时，旧确认都会失效。轨迹只记录是否提供授权，不记录完整确认凭证。

## 4. 本地端到端排查与修复

第一次真实兑换进入 `EXCHANGE_PROCESSING` 后最终失败。直接证据是 MySQL 的 2 号奖品分片库存总和为 `60`，但 Redis 的 `award_inventory_split:2` 长度为 `0`，Consumer 因没有候选分片将订单置为失败。根因不是 Agent 确认，而是默认只预热 6 号奖品。

修复过程：

1. 将默认预热奖品改为 `1,2,3,4,5,6`，仍由 `CacheWarmer` 从 MySQL 重建缓存，不手工伪造结果。
2. 修复 Canal 的过期 binlog 位点，使客户端重新从当前日志文件消费。
3. 发现分片库存能够同步但积分不同步，最终定位到 `RDSBinlog` 写入 `user_currency:<id>`，而业务读取 `user:currency:<id>`。
4. 统一积分键名，并用构造 Canal RowData 的单元测试锁定行为。

最终使用用户 8 真实兑换 2 号奖品：

| 证据 | 兑换前 | 兑换后 |
| --- | ---: | ---: |
| MySQL 用户积分 | 2300 | 800 |
| Redis 用户积分 | 2300 | 800 |
| MySQL 分片库存总和 | 58 | 57 |
| Redis 分片库存总和 | 58 | 57 |
| `user_award.status` | 无记录 | 1 |

同时生成 1 条业务幂等记录，结果查询接口返回兑换成功。Redis 的积分和库存均在不重启应用、不再次预热的情况下与 MySQL 一致，证明本次结果来自实时 Canal 同步。

## 5. 验证证据与边界

- Python 全量测试 `54/54` 通过，其中 Redis 专项测试使用两个独立客户端验证配置接入、共享可见和跨实例原子消费。
- Java `mvn test` 通过，新增 `RDSBinlogTest` 直接验证积分写入 `user:currency:7`。
- React TypeScript 校验与 Vite 生产构建通过。
- 模型完整回归 `23/25`，安全检查 `25/25`；受控兑换定向复验 `2/2`。两个剩余失败分别是拒绝措辞评分和多调用一次资格查询，不属于越权写入。
- 只接入旧事务消息链路，没有恢复或引入 Redis 预扣新链路。
- HTTP 服务默认使用 Redis 共享确认状态；内存实现仅用于显式配置和快速单元测试。Redis 不可用时启动失败，不静默降级为单进程状态。
- Java 写入口已具备持久化请求级幂等；它与消费侧业务幂等分层，重复 HTTP 请求不会再次调用旧兑换链路。
- 本地演示身份来自前端用户 ID；生产系统必须改为由登录态或网关注入可信身份。
