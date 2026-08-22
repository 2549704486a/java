# 评测原始结果

本目录保存评测 Runner 生成的 JSON。每个文件包含评测环境、自动评分、最终回答、模型声明的 Tool 调用、实际 Tool 执行轨迹、Fixture 后端调用和完整消息轨迹，不保存 API Key。

结构化 `tool_execution_trace` 不保存完整业务响应，但用于离线审计的 LangChain `trace` 会保留 ToolMessage 内容。提交 Git 的结果应只使用 Fixture 或本地演示数据；真实用户数据必须先脱敏，不能直接进入结果目录。

- `tool_trace_multiskill_20260820.json`：新增四个多 Skill 路由场景的定向验证，结果 `4/4`。
- `tool_trace_full_20260820.json`：接入结构化执行轨迹后的 22 个固定场景全量回归，结果 `22/22`。
- `rag_retrieval_hard_cases_20260822.json`：旧阈值下的困难检索原始结果，保留口语用例误拒答证据。
- `rag_retrieval_hard_cases_threshold_20260822.json`：阈值校准后的 24 条完整检索结果。
- `rag_retrieval_post_rebuild_20260822.json`：重建索引后的错别字、口语定向复验。
- `rag_agent_faithfulness_hard_cases_20260822.json`：困难 Agent 用例的原始结果，保留歧义口语问题错误路由证据。
- `rag_agent_ra09_corrected_20260822.json`：澄清用例语义后的单条复验，不替换原始失败证据。
- `rag_agent_faithfulness_final_scoped_20260822.json`：最终 11 条 Agent 评测；忠实度只统计适用的 7 条 RAG 规则用例。
- `rag_retrieval_query_normalization_20260822.json`：受控 Query 标准化和双路召回的 4 条困难用例定向结果，Top1 为 `4/4`。
- `complex_planning_baseline_20260822.json`：长期目标复杂规划 7 条基线，结果 `6/7`；P01 保留任务名称转 ID 导致重复查询的原始轨迹。
- `complex_planning_baseline_p08_20260822.json`：显式奖品多约束基线；答案碰巧满足任务约束，但约束没有进入 Tool 参数。
- `complex_planning_final_20260822.json`：任务契约修改后的 8 条结果，保留参数同义表达评分假阴性和期限遗漏证据，其余用例 `6/6`。
- `complex_planning_final_constraints_20260822.json`：修正评分同义参数和期限表达后的 P01、P08 定向结果，`2/2`。
- `campaign_planning_baseline_20260822.json`：8 条冻结运营场景的确定性基线；权限隔离 `16/16`、数据引用 `21/21`、约束满足 `32/32`、草案完整性 `20/20`。
- `operator_rag_vector_baseline_20260822.json`：15 条运营知识纯向量检索基线；Top1、Hit@3、负样本拒答率和引用结构有效率均为 `100%`，不包含 Agent 回答评测。
