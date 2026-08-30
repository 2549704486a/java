# Agent 项目文档导航

> 文档按用途隔离。开发时优先看代码文档，准备面试时按需加载面试文档，避免把实现细节和面试表达混在一起。

## 0. 从这里开始

| 文档 | 用途 |
| --- | --- |
| [`../AGENTS.md`](../AGENTS.md) | Coding Agent 的仓库导航、事实优先级、不可破坏边界和开发协议 |
| [`../PRODUCT.md`](../PRODUCT.md) | 当前产品用户、核心旅程、能力基线、指标口径和明确非目标 |
| [`../openspec/changes/`](../openspec/changes/) | 跨服务、高风险或存在非显然取舍时使用的 OpenSpec 变更工件 |
| [`../openspec/config.yaml`](../openspec/config.yaml) | OpenSpec 的项目上下文、提案规则、设计原则和任务约束 |

新任务先读根目录 `AGENTS.md`，再按其中的渐进加载顺序进入项目上下文和当前路线图。不要把本目录当作需要顺序通读的教程。

## 1. 代码与工程文档

| 目录 | 用途 |
| --- | --- |
| `agent-context/` | 当前项目事实、旧链路、代码索引和 Agent 接入边界 |
| `agent-design/` | Agent 产品需求、工具契约、评测用例和阶段实现说明 |
| `../openspec/specs/` | 已归档并生效的行为契约；不能用活动变更代替当前事实 |
| `../openspec/changes/` | 复杂功能实施前的问题、行为规格、方案取舍、任务与回滚边界 |
| `agent-learning/` | 历史技术学习清单和专题笔记；不参与开发规划，仅在明确学习或复习时按需使用 |
| `agent-journal/` | 按完成时间记录需求、开发、测试、学习和排查任务的简要日记 |
| `../agent-service/README.md` | Python 服务安装、配置、运行和测试命令 |
| `../agent-service/skills/` | Skill 的触发条件、执行步骤、错误处理和安全边界 |
| `agent-design/05_本地环境一键启动.md` | 本地中间件与 Java 应用的一键启动、状态检查和日志位置 |
| `agent-design/08_Agent评测体系升级.md` | 从固定回归走向盲测、重复试验、混合评分和线上反馈闭环的升级方案 |
| `agent-design/09_Skill运行时标准化.md` | Skill 目录披露、SKILL.md 正文按需加载、Tool 与 Service 的真实边界 |
| `agent-design/10_Agent服务化.md` | FastAPI 接口、多用户身份隔离、有界 Agent 缓存、生命周期和请求追踪 |
| `agent-design/11_短期记忆与会话隔离.md` | InMemorySaver、thread_id、会话隔离、串行执行和会话 LRU |
| `agent-design/12_奖品推荐Skill.md` | 奖品推荐 Skill 的模型执行说明、业务 Tool、确定性推荐 Service 和数据契约 |
| `agent-design/13_本地演示数据基线.md` | 可重复执行的业务演示数据、关键用户故事、一致性约束和重置顺序 |
| `agent-design/14_Tool调用链可观测性.md` | 请求级 Tool 结构化轨迹、Skill 加载顺序、结果摘要和耗时统计 |
| `agent-design/15_受控兑换Skill需求与状态机.md` | 高风险兑换的二次确认、一次性凭证、状态机和职责边界 |
| `agent-design/16_受控兑换Tool契约.md` | 准备与确认 Tool、Java 写入适配、重试和审计契约 |
| `agent-design/17_受控兑换评测用例.md` | 授权、重复提交、并发、未知结果和回归评测场景 |
| `agent-design/18_奖品中心与Agent前端.md` | React 奖品中心、Agent 对话、dashboard 聚合接口和同源部署边界 |
| `agent-design/19_受控兑换Skill实现.md` | 受控兑换 Skill、确定性 Service、一次性确认存储和旧链路 POST 适配 |
| `agent-design/20_Agent课程能力落地路线图.md` | 项目最高优先级、课程能力覆盖、分阶段实施顺序和动态调整规则 |
| `agent-design/21_Java兑换请求持久化幂等.md` | Agent 写入口的请求占位、响应重放、冲突检测和未知状态边界 |
| `agent-design/22_Redis确认凭证共享存储.md` | 确认授权的 Redis Key 模型、Lua 原子迁移、TTL 和跨实例验证 |
| `agent-design/23_Agent可信用户身份.md` | JWT 身份来源、Token 契约、前端登录边界和越权回归 |
| `agent-design/24_评测集隔离与重复试验.md` 至 `31_RAG索引新鲜度与答案忠实度.md` | 评测隔离、成本口径以及用户侧 RAG 的治理闭环 |
| `agent-design/32_兑换目标与长期偏好.md` 至 `36_复杂规划评测与任务约束.md` | 长期记忆、目标驱动规划和任务约束 |
| `agent-design/37_运营活动草案最小闭环.md` 至 `47_运营意图路由与当前轮引用隔离.md` | 运营草案、身份、知识、审核发布和意图治理 |
| `agent-design/48_Agent开发问题与解决方案复盘.md` 至 `50_Agent核心代码调用全景.md` | 问题复盘、业务域目录和代码调用全景 |
| `agent-design/51_活动执行与效果观测技术方案.md` 至 `59_Skill事实审计与运行时纠偏.md` | 活动执行、实验、投放、效果分析、运行时 Harness、Prompt/Skill 纠偏，以及 Skill 运行时事实纠偏 |

这些文档服务于开发、调试和代码评审，可以记录具体路径、接口、状态码和运行命令。

开始或恢复开发时，查看 `agent-design/20_Agent课程能力落地路线图.md` 确认当前阶段和开发优先级。`agent-learning/` 不再默认加载或日常维护，只有用户明确要求学习、复习或整理技术专题时才按需使用。

每项独立任务完成并验证后，必须同步更新路线图中的课程覆盖情况，再在 `agent-journal/任务日记.md` 追加完成时间和任务概述；不要把尚未完成的计划提前写入日记。

## 2. 面试文档

| 目录 | 用途 |
| --- | --- |
| `agent-interview/` | 只沉淀已有代码或测试证据支撑的面试问题、回答要点和工程经验 |

面试文档不复制全部代码，不把尚未实现的规划包装成项目成果。每完成一个关键能力，只增加少量可复用内容；项目结束后再基于完整实现统一总结。
