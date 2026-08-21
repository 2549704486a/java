# 奖品中心与 Agent 对话前端

这是积分激励项目的本地演示页面，包含奖品中心、可信身份验证和 Agent 对话。页面读取实时积分与奖品资格，但不直接调用兑换写接口。

## 1. 一键运行

在项目根目录执行：

```powershell
.\start-local.ps1
```

脚本会在启动 Agent 前自动完成前端依赖安装和生产构建。全部服务就绪后访问：

```text
http://127.0.0.1:8090/
```

首次进入前，在 `agent-service` 目录签发本地用户 Token，并粘贴到页面：

```powershell
.\.venv\Scripts\python.exe -m app.auth --user-id 10
```

只有前端源码或配置比 `dist/index.html` 更新时才会重新构建。使用 `-Rebuild` 可强制重建，使用 `-SkipWeb` 可跳过前端构建。

## 2. 前端开发

先保证 Java 服务和 Agent 服务已经运行，再执行：

```powershell
cd D:\工作\incentive-事务消息\web-ui
npm install
npm run dev
```

开发服务器默认地址为 `http://127.0.0.1:5173/`，Vite 会把 `/v1` 和 `/health` 代理到 `http://127.0.0.1:8090`。

生产构建：

```powershell
npm run build
```

构建产物位于 `web-ui/dist/`，由 FastAPI 以同源方式托管，不需要额外配置 CORS。

## 3. 页面能力与边界

- `/v1/me` 验证 Bearer Token 并返回当前可信用户。
- `/v1/dashboard` 聚合当前用户积分和奖品列表，减少浏览器对 Java 信封协议的了解。
- `/v1/chat` 延续现有 Agent 会话，支持积分查询、奖品推荐和任务规划。
- 奖品卡片的操作会生成咨询或准备兑换问题，真实兑换仍必须经过一次性确认凭证。
- 浏览器不能通过参数切换用户；Token 只保存在当前标签页的 `sessionStorage`。

## 4. 验证

```powershell
npm run build
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8090/
$token = ..\agent-service\.venv\Scripts\python.exe -m app.auth --user-id 10
Invoke-RestMethod `
    -Uri http://127.0.0.1:8090/v1/dashboard `
    -Headers @{ Authorization = "Bearer $token" }
```

当前使用 Vite 5 以兼容本机 Node.js 18。页面生产运行不启动 Vite 开发服务器。
