# Agent 项目文档导航

> 文档按用途隔离。开发时优先看代码文档，准备面试时按需加载面试文档，避免把实现细节和面试表达混在一起。

## 1. 代码与工程文档

| 目录 | 用途 |
| --- | --- |
| `agent-context/` | 当前项目事实、旧链路、代码索引和 Agent 接入边界 |
| `agent-design/` | Agent 产品需求、工具契约、评测用例和阶段实现说明 |
| `agent-learning/` | 技术学习清单、学习状态和结合当前代码展开的专题笔记 |
| `agent-journal/` | 按完成时间记录需求、开发、测试、学习和排查任务的简要日记 |
| `../agent-service/README.md` | Python 服务安装、配置、运行和测试命令 |
| `../agent-service/skills/` | Skill 的触发条件、执行步骤、错误处理和安全边界 |
| `agent-design/05_本地环境一键启动.md` | 本地中间件与 Java 应用的一键启动、状态检查和日志位置 |
| `agent-design/08_Agent评测体系升级.md` | 从固定回归走向盲测、重复试验、混合评分和线上反馈闭环的升级方案 |
| `agent-design/09_Skill运行时标准化.md` | SKILL.md 的运行时注册、契约校验、渐进披露和版本追踪 |
| `agent-design/10_Agent服务化.md` | FastAPI 接口、多用户身份隔离、有界 Agent 缓存、生命周期和请求追踪 |
| `agent-design/11_短期记忆与会话隔离.md` | InMemorySaver、thread_id、会话隔离、串行执行和会话 LRU |
| `agent-design/12_奖品推荐Skill.md` | 第二个业务 Skill、确定性推荐规则、嵌套数据契约和多 Skill 路由评测 |
| `agent-design/13_本地演示数据基线.md` | 可重复执行的业务演示数据、关键用户故事、一致性约束和重置顺序 |
| `agent-design/14_Tool调用链可观测性.md` | 请求级 Tool/Skill 结构化轨迹、结果摘要、耗时统计和轨迹评分 |
| `agent-design/15_受控兑换Skill需求与状态机.md` | 高风险兑换的二次确认、一次性凭证、状态机和职责边界 |
| `agent-design/16_受控兑换Tool契约.md` | 准备与确认 Tool、Java 写入适配、重试和审计契约 |
| `agent-design/17_受控兑换评测用例.md` | 授权、重复提交、并发、未知结果和回归评测场景 |
| `agent-design/18_奖品中心与Agent前端.md` | React 奖品中心、Agent 对话、dashboard 聚合接口和同源部署边界 |
| `agent-design/19_受控兑换Skill实现.md` | 一次性确认存储、旧链路 POST 适配、状态语义和安全测试证据 |

这些文档服务于开发、调试和代码评审，可以记录具体路径、接口、状态码和运行命令。

开始或恢复开发时，先查看 `agent-learning/00_技术学习清单.md`。它负责防止遗漏代码中已经使用、但尚未系统理解或总结的技术点。

每项独立任务完成并验证后，在 `agent-journal/任务日记.md` 追加完成时间和任务概述；不要把尚未完成的计划提前写入日记。

## 2. 面试文档

| 目录 | 用途 |
| --- | --- |
| `agent-interview/` | 只沉淀已有代码或测试证据支撑的面试问题、回答要点和工程经验 |

面试文档不复制全部代码，不把尚未实现的规划包装成项目成果。每完成一个关键能力，只增加少量可复用内容；项目结束后再基于完整实现统一总结。
