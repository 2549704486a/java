# 受控业务知识源

这里保存未来 RAG 索引的原始知识，不保存向量数据库文件。当前阶段只建立知识源治理，不会把这些文档自动注入模型上下文。

## 收录规则

- 只收录稳定规则、状态解释、操作指引和常见问题。
- 当前积分、库存、价格、活动时间、任务状态、兑换资格和订单结果必须走 Tool，不得写成知识事实。
- 每篇文档必须有 YAML Front Matter、项目内权威来源和 `实时信息边界`。
- 新增或修改文档后必须审核内容、更新 `manifest.json` 中的 SHA-256，再运行目录校验。
- 向量库、Embedding 结果和临时检索输出属于派生产物，不提交到本目录。

## 校验命令

```powershell
cd D:\工作\incentive-事务消息\agent-service
.\.venv\Scripts\python.exe -m app.knowledge_catalog
```

只有校验通过的 `active` 文档，才允许进入下一阶段的切分与索引流程。
