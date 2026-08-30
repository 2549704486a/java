# Redis 确认凭证共享存储

> 这一阶段解决的是“用户在 Agent 实例 A 准备兑换，却把确认请求发到实例 B 时，授权是否仍然有效且只能消费一次”。确认凭证属于高风险写操作的服务端授权状态，不能依赖对话历史，也不能只放在单进程内存中。

## 1. 存储边界

内存实现仍保留给快速单元测试；HTTP 服务通过 `Settings.from_env()` 默认使用 Redis 实现。

| 数据 | Redis 结构 | 用途 |
| --- | --- | --- |
| 凭证记录 | `agent:exchange:confirmation:record:{confirmation_id}` Hash | 保存用户、会话、奖品、摘要、有效期和状态 |
| 会话待确认指针 | `agent:exchange:confirmation:pending:{session_hash}` String | O(1) 找到当前会话唯一的待确认凭证 |
| 容量索引 | `agent:exchange:confirmation:records` ZSet | 按创建时间治理容量和清理陈旧成员 |

会话 ID 转换为不直接暴露原文的键片段后进入 Redis Key；完整会话 ID 仍保存在凭证 Hash 中用于身份校验。业务 Redis 与 Agent 状态共用实例时，通过固定前缀隔离命名空间。

## 2. 原子状态迁移

`create`、`claim`、`finish`、`cancel` 和待确认查询中的过期处理都由 Lua 在 Redis 内一次完成。最重要的是 `claim`：

```text
读取凭证
  -> 校验 user_id 与 session_id
  -> 校验 PREPARED、有效期和请求回合
  -> 原子修改为 EXECUTING
  -> 删除会话待确认指针
  -> 只有状态迁移成功的实例可以调用 Java 兑换接口
```

多个 Agent 实例同时确认时，Redis 会串行执行 Lua。第一个请求看到 `PREPARED` 并改为 `EXECUTING`；后续请求只能看到已使用状态，因此不能再次调用 Java。

新建凭证时会在同一段 Lua 中取消该会话旧的 `PREPARED` 记录，再写入新记录与待确认指针，避免出现两个同时有效的授权。

## 3. TTL 与停机语义

- 待确认指针的 TTL 等于用户确认窗口，默认 `120` 秒。
- 凭证记录默认保留 `3600` 秒，使过期或重复请求仍能得到“已过期/已使用”，而不是立即退化成“不存在”。
- 时间以 Redis `TIME` 为准，避免不同 Agent 主机时钟偏差影响同一凭证。
- Agent 停机只关闭 Redis 连接，绝不清空共享凭证；显式 `clear()` 只供隔离测试和运维清理。
- Java 的持久化 `Idempotency-Key` 仍是下一层保护。即使 Python 在极端故障下重复提交，Java 也不会重复调用旧兑换链路。

## 4. 配置

```dotenv
EXCHANGE_CONFIRMATION_STORE=redis
EXCHANGE_CONFIRMATION_REDIS_URL=redis://127.0.0.1:6379/0
EXCHANGE_CONFIRMATION_REDIS_PREFIX=agent:exchange:confirmation
EXCHANGE_CONFIRMATION_TTL_SECONDS=120
EXCHANGE_CONFIRMATION_RETENTION_SECONDS=3600
EXCHANGE_CONFIRMATION_CAPACITY=10000
```

生产环境应通过密钥管理或部署环境注入带密码的 Redis URL，不能提交真实密码。Redis 不可用时服务启动失败，不静默退回内存模式，否则多实例安全语义会悄悄失效。

## 5. 验证证据

- 原有内存 Store 和 Agent 回归全部通过。
- Redis 专项测试使用两个独立客户端，共享读取准备记录和完成状态。
- `20` 个线程交替使用两个 Store 实例争抢同一凭证，结果为 `1` 个 `CONFIRMATION_CLAIMED`、`19` 个 `CONFIRMATION_ALREADY_USED`。
- 已验证跨实例新建凭证会取消旧凭证，身份/会话不可串用，同一请求回合不可自行确认，过期状态准确返回。
- 已验证关闭一个 Store 只关闭连接，另一个 Store 仍能读取共享记录。
- 启用 Redis 集成测试后的全量结果为 `54/54`。

运行方式：

```powershell
$env:RUN_REDIS_INTEGRATION_TESTS = '1'
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
Remove-Item Env:RUN_REDIS_INTEGRATION_TESTS
```
