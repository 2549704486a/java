# Agent 可信用户身份

> 这一阶段解决的是“浏览器能否把 `user_id` 改成别人并以对方身份查询或兑换”。改造后，浏览器只能提交服务端签名的访问令牌，Agent 从令牌声明中取得用户身份，业务请求不再接受调用者指定用户。

## 1. 调用链

```text
本地可信签发命令
  -> 使用 AGENT_AUTH_SECRET 签发 HS256 JWT
  -> JWT 包含 issuer、audience、subject、uid、签发时间和过期时间

Browser
  -> Authorization: Bearer <JWT>
FastAPI
  -> 验证签名、签发方、受众、有效期和 subject/uid 一致性
  -> 得到 AuthenticatedUser.user_id
  -> 将可信 user_id 传给 AgentRuntime
  -> Agent、会话、确认凭证和 Java Tool 均绑定该用户
```

`POST /v1/chat` 的请求体现在只包含 `message` 和可选 `session_id`；`GET /v1/dashboard` 也不再包含用户路径参数。即使调用者额外注入 `user_id`，Pydantic 的 `extra="forbid"` 也会在进入运行时前拒绝请求。

## 2. Token 契约

| 声明 | 作用 |
| --- | --- |
| `iss` | 限定可信签发方，防止接受其他系统碰巧同格式的 Token |
| `aud` | 限定 Token 只能用于当前 Agent Web |
| `sub` | 标准主体，格式为 `user:<uid>` |
| `uid` | 业务用户 ID，是运行时唯一采用的用户来源 |
| `iat` / `exp` | 限制签发和有效时间 |
| `jti` | 标识一次签发，便于后续审计或撤销扩展 |

缺失 Token、Header 格式错误、签名错误、过期以及身份声明不一致均返回 `401`，同时保留 `X-Request-ID` 便于排查。

## 3. 本地使用

在 `agent-service/.env` 配置至少 32 字符的随机密钥：

```dotenv
AGENT_AUTH_SECRET=本地随机密钥
AGENT_AUTH_ISSUER=incentive-agent
AGENT_AUTH_AUDIENCE=incentive-agent-web
AGENT_ACCESS_TOKEN_TTL_SECONDS=3600
```

服务启动后，在 `agent-service` 目录为演示用户签发 Token：

```powershell
$token = .\.venv\Scripts\python.exe -m app.auth --user-id 10
```

浏览器页面只把 Token 保存在 `sessionStorage`，关闭标签页后清除。这里没有公开“输入用户 ID 即登录”的接口，否则只是把原来的越权入口换了一个位置。

## 4. 边界

- 当前 HS256 签发命令服务于本地演示；生产环境应接入真实登录系统，并优先使用 OIDC/JWKS 验证非对称签名 Token。
- 浏览器存储 Token 仍需防范 XSS；生产 Web 更适合由 BFF 使用 `HttpOnly + Secure + SameSite` Cookie 管理会话。
- 本阶段保护的是 Agent HTTP 边界。Java 写接口仍应只暴露在受控内网，并在生产环境增加服务间认证，不能直接开放给浏览器。
- Token 只证明“用户是谁”；一次性确认、Redis 原子领取和 Java 幂等仍分别解决“用户是否授权”和“操作是否只执行一次”。

## 5. 验证

- JWT 单元测试覆盖签发还原、缺失 Header、错误格式、过期、错误签名和 `sub/uid` 不一致。
- Web 契约测试证明 Token 中的用户进入 `AgentRuntime`，请求体注入 `user_id` 被拒绝。
- Python 全量离线回归 `60/60` 通过；7 个需真实 Redis 的集成用例按开关跳过。
- React TypeScript 检查和 Vite 生产构建通过。
