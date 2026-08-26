---
title: ""
status: draft
owner: ""
created: YYYY-MM-DD
updated: YYYY-MM-DD
---

# Feature Spec: <用户可理解的功能名称>

> Spec 用于收敛复杂产品决策，不是把聊天记录、技术设想和代码清单全部搬进文档。跨服务、改变状态机或权限、引入数据结构、需求存在非显然取舍时使用；局部修复和纯文档调整无需创建。

## 1. Problem

- 谁遇到了什么问题？
- 问题发生在什么场景？
- 当前行为为什么不能满足需求？
- 如果不解决，会产生什么用户或业务影响？

不要从“我们想引入某项技术”开始描述问题。

## 2. Evidence

### 2.1 Confirmed Facts

| 事实 | 证据位置 | 可信度说明 |
| --- | --- | --- |
|  | 源码、接口、日志或可复现步骤 |  |

### 2.2 Hypotheses

| 假设 | 为什么值得验证 | 如何证伪 |
| --- | --- | --- |
|  |  |  |

### 2.3 Alternative Explanations

- 还可能由什么原因导致？
- 当前证据为什么暂时支持或排除它？

### 2.4 Open Questions

- 哪些信息仍未知？
- 未知项是否阻塞实施，还是可以带着明确风险继续？

Fixture、Simulated、计划值和模型判断必须明确标注，不能写成生产事实。

## 3. Goal And Non-Goals

### Goal

- 用户完成后能获得什么可观察结果？
- 本次改变哪个行为，而不是新增哪些文件？

### Non-Goals

- 本次明确不解决什么？
- 哪些相邻需求留到有证据时再处理？

## 4. Options And Decision

| 方案 | 收益 | 成本与风险 | 是否选择 |
| --- | --- | --- | --- |
| 最小方案 |  |  |  |
| 替代方案 |  |  |  |
| 保持现状 |  |  |  |

**Decision：**

说明为什么当前方案最适合，而不只是为什么它可行。存在影响产品边界、数据兼容或不可逆迁移的取舍时，实施前先与用户对齐。

## 5. User Flow

```text
入口
  -> 用户或运营动作
  -> 系统反馈
  -> 异常与恢复路径
  -> 最终可见结果
```

## 6. Requirements

### Functional Requirements

1. <!-- requirement -->

### Business And Safety Constraints

- 身份与权限：
- 动态事实来源：
- 写操作确认与幂等：
- 审计与可追踪性：
- Fixture/Simulated 边界：

### Failure Semantics

| 场景 | 系统行为 | 用户可见表达 | 是否可重试 |
| --- | --- | --- | --- |
|  |  |  |  |

## 7. Acceptance Criteria

尽量使用可以观察和复现的行为，不以“代码已写完”作为验收条件。

1. Given ... When ... Then ...
2. <!-- acceptance criterion -->

## 8. Implementation Map

| 模块 | 预计职责变化 | 不应承担的职责 |
| --- | --- | --- |
| Java 业务服务 |  |  |
| Agent Service |  |  |
| Web UI |  |  |
| 文档或数据迁移 |  |  |

这里只记录职责和影响面，不预先规定没有证据支撑的抽象层。

## 9. Verification

| 验收项 | 最小检查方式 | 预期证据 |
| --- | --- | --- |
| 核心成功路径 |  |  |
| 关键失败路径 |  |  |
| 权限或状态边界 |  |  |
| 未受影响范围 |  |  |

只运行与改动直接相关的检查；需要全量回归时单独说明原因。

## 10. Risks And Rollback

| 风险 | 触发信号 | 缓解方式 |
| --- | --- | --- |
|  |  |  |

**Rollback：** 说明如何停止新行为、恢复旧状态，以及数据是否需要兼容处理。

## 11. Outcome

实施完成后填写，不能提前把计划写成结果。

### Implemented

- <!-- implemented behavior -->

### Evidence

- <!-- evidence location or result -->

### Remaining Risks

- <!-- remaining risk -->

### Out Of Scope

- <!-- intentionally excluded work -->
