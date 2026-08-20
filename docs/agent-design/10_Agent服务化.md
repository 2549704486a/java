# Agent 服务化

> CLI 适合开发者手动验证，但前端和其他服务不能稳定调用一个等待键盘输入的进程。本阶段把 Agent 包装成常驻 HTTP 服务，同时解决多用户身份隔离、资源复用、缓存上限、请求追踪和错误脱敏问题。

## 1. 接口形态

```text
POST /v1/chat
  -> Pydantic 校验 user_id 和 message
  -> 生成或接收 X-Request-ID
  -> AgentRuntime 按 user_id 获取 Agent
  -> LangChain Agent 选择 Tool/Skill
  -> Java 只读业务接口
  -> 返回 answer 和 elapsed_ms
```

`GET /health` 只反映 Agent 进程是否完成初始化，并返回模型名、缓存数量和 Skill 版本，不主动请求 Java 或模型服务。

## 2. 为什么不能全用户共用一个 Agent

当前 Tool 在创建时通过闭包绑定 `user_id`。这样模型无法在参数中伪造其他用户，但也意味着“用户 10 的 Agent”不能拿给用户 11 使用。

`AgentRuntime` 因此按 `user_id` 缓存 Agent：

- 同一用户后续请求复用同一执行图。
- 不同用户拥有各自绑定身份的 Tool。
- 所有 Agent 共享一个 `BusinessApiClient`，复用 HTTP 连接池。
- 缓存达到 `AGENT_CACHE_SIZE` 后，淘汰最久未使用的用户 Agent。

这个缓存只复用模型与 Tool 编排对象，**不保存历史消息**。当前接口还是单轮对话，多轮记忆将在下一阶段单独设计。

## 3. 并发与生命周期

`/v1/chat` 使用同步 FastAPI 路由。模型和 Java HTTP 调用是阻塞操作，FastAPI 会将同步路由放入线程池，避免阻塞 ASGI 事件循环。

服务启动时创建：

- 一个 `SkillRegistry`。
- 一个共享 `BusinessApiClient`。
- 一个有界 Agent LRU 缓存。

服务关闭时清空缓存并关闭共享 HTTP Client，避免连接泄漏。

## 4. 可观测性与错误边界

调用方可以传入合法的 `X-Request-ID`；未提供或格式不合法时由服务生成。日志记录：

```text
agent_request_started request_id=... user_id=... message_length=...
agent_cache_hit/agent_cache_miss/agent_cache_evicted user_id=...
agent_request_completed request_id=... user_id=... elapsed_ms=...
```

服务端保留完整异常堆栈，但响应统一返回：

```json
{
  "request_id": "...",
  "code": "AGENT_SERVICE_UNAVAILABLE",
  "message": "Agent 服务暂时不可用，请稍后重试"
}
```

这样既能通过请求 ID 排查问题，也不会向调用方泄露模型服务地址、内部堆栈或密钥。

## 5. 当前边界

- 只有只读聊天接口，不增加兑换写能力。
- 没有认证网关，`user_id` 暂由调用方传入；生产环境必须由可信登录态解析，不能信任请求体。
- 没有会话记忆，不支持跨请求自动继承奖品或任务偏好。
- 没有跨进程缓存；启动多个服务实例时，各实例维护自己的 Agent LRU。

这些限制被明确保留，避免把本地可运行版本误称为生产级服务。
