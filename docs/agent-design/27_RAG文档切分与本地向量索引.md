# RAG 文档切分与本地向量索引

> 本阶段把经过治理的业务知识加工成可检索的 Chunk，并建立可重复生成的本地 Chroma 索引。它解决的是“知识怎样进入索引”，还没有把检索结果接入 Agent 回答。

## 1. 当前实现

入口位于 `agent-service/app/knowledge_index.py`，处理链路为：

```text
manifest.json
  -> KnowledgeCatalog 校验并加载 active 文档
  -> 按 Markdown 标题拆出语义章节
  -> 对过长章节递归切分
  -> Embedding
  -> 重建同名 Chroma 集合
```

当前 3 篇知识文档共生成 12 个 Chunk。默认参数为：

- `chunk_size=400`：单个 Chunk 最多约 400 个字符。
- `chunk_overlap=60`：相邻的过长文本切片保留最多 60 个字符的重叠上下文。
- 分隔顺序：段落、换行、中文句号、分号、逗号、空格，最后才按字符切分。

这里采用“两阶段切分”：先按标题保留章节语义，再只对过长章节递归切分。相比直接按固定长度切割，它能减少规则标题与正文被拆散的问题。

## 2. Chunk 元数据

每个 Chunk 都携带以下可追溯信息：

| 字段 | 作用 |
| --- | --- |
| `knowledge_id` | 标识来自哪一类知识 |
| `knowledge_version` | 标识来源文档版本 |
| `catalog_version` | 标识本次知识目录版本 |
| `title` | 面向用户的文档标题 |
| `source_path` | 项目内相对路径，便于迁移和引用 |
| `source_refs` | 对应的项目源码或配置依据 |
| `topics`、`audience` | 后续检索过滤所需标签 |
| `fact_scope` | 说明文档只包含稳定规则，不承担实时事实查询 |
| `heading_1/2/3` | 记录 Chunk 所属章节 |
| `chunk_index`、`chunk_id` | 支持稳定排序、定位和重复建库 |

元数据的意义不是“字段越多越好”，而是让后续回答能够说明知识来自哪里，并支持按主题、版本或范围过滤。

## 3. 可重复建库

`KnowledgeIndexBuilder` 先把当前 active 文档完整写入临时集合，全部成功后才替换指定的正式集合，不会删除目录中的其他集合和用户文件。这样既能避免新旧 Chunk 混在一起，也能保证外部向量化失败时继续保留上一版可用索引。

本地索引目录默认为 `agent-service/knowledge/index/`，它属于可重新生成的派生产物，已加入 `.gitignore`，不提交到 Git。

配置项位于 `.env`：

```dotenv
RAG_EMBEDDING_API_KEY=
RAG_EMBEDDING_BASE_URL=
RAG_EMBEDDING_MODEL=text-embedding-3-small
RAG_EMBEDDING_BATCH_SIZE=10
RAG_CHUNK_SIZE=400
RAG_CHUNK_OVERLAP=60
RAG_INDEX_DIR=knowledge/index
RAG_COLLECTION_NAME=incentive-business-rules
```

如果 Embedding 服务与对话模型使用同一套兼容接口，可以不单独填写 RAG Key 和地址，运行时会复用 `LLM_API_KEY` 与 `LLM_BASE_URL`。模型名称仍应单独确认，因为聊天模型和 Embedding 模型职责不同。

`RAG_EMBEDDING_BATCH_SIZE` 控制一次提交给 Embedding 服务的文本数。当前阿里云兼容接口单批最多接收 `10` 条，因此默认设置为 `10`；它只影响离线建库批次，不改变 Chunk 数量和在线检索结果。

## 4. 使用方式

只检查切分，不调用外部模型：

```powershell
cd D:\工作\incentive-事务消息\agent-service
.\.venv\Scripts\python.exe -m app.knowledge_index inspect-chunks
```

配置 Embedding 服务后构建持久化索引：

```powershell
.\.venv\Scripts\python.exe -m app.knowledge_index build
```

本阶段没有配置真实 Embedding Key，因此没有把某个外部模型的索引结果当作交付物。测试使用确定性本地向量替身验证切分、建库、重复构建和检索流程；另用磁盘目录验证 Chroma 能够持久化工作。

## 5. 验证结果与边界

- 切分检查：`3` 篇文档生成 `12` 个 Chunk，最长 Chunk 未超过默认上限。
- 定向测试：`3/3` 通过，覆盖元数据、非法重叠参数、重复构建和规则检索。
- 持久化冒烟：磁盘索引构建成功，查询兑换结果规则命中 `exchange-rules-and-status`。
- 全量回归：`76` 个测试执行，`69` 个通过，`7` 个 Redis 集成测试按开关跳过。

当前尚未完成：

- Agent 运行时还不能调用知识检索。
- 回答还不会返回来源引用。
- 尚未定义低相关结果的拒答阈值。
- 尚未建立检索命中率、引用正确性和无答案用例。

下一步应新增只读知识检索能力，先返回“命中的原文片段 + 来源元数据”，再决定如何将其接入 Agent，避免一开始就把检索、生成和评分揉在一起。
