# GraphRAG 推广决策报告

**版本**：Phase 3 终版  
**日期**：2026-07-10  
**作者**：CloudBrief 工程与算法团队  
**关联文档**：
- `_bmad-output/specs/spec-cloudbrief-graphrag/poc-report.json`
- `_bmad-output/specs/spec-cloudbrief-graphrag/epic3-breakdown.md`
- `backend/data/second_kb_pilot_report_8.json`
- `backend/data/second_kb_pilot_recall_report_8.json`
- `backend/scripts/benchmark_graph_incremental.py`

---

## 执行摘要

| 维度 | 结论 |
|---|---|
| 关系型问题准确率 | Phase 1 PoC 样本：GraphRAG 86.67% vs 向量 RAG 93.33%；第二个知识库试点：GraphRAG 关系召回 55%（基于 gold set 字符串匹配），子图召回 100%。|
| 耗时开销 | GraphRAG 平均端到端延迟约为向量 RAG 的 2 倍；增量更新耗时约为全量重建的 14.83%。|
| 成本 | 主要增量成本为 LLM 抽取与 Neo4j 存储/查询；当前 DashScope API 稳定性对生产环境构成风险。|
| 工程成熟度 | Phase 2/3 已完成开关、schema 配置、异步构建、增量更新、监控告警、Dashboard 卡片与自动回退。|
| **建议** | **继续试点，暂不全面推广**。优先解决实体链接稳定性、LLM 成本与 reranker 可用性，再在 1–2 个真实业务知识库上验证后扩大范围。|

---

## 1. 背景与目标

CloudBrief 支持副驾希望在 Enterprise RAG 流程中引入 GraphRAG，以改善跨文档、跨实体的关系型问题回答能力。本项目分三阶段推进：

- **Phase 1（概念验证）**：验证抽取质量、生成增强效果与 schema 自动推荐。
- **Phase 2（工程 MVP）**：将 GraphRAG 集成到主流程，提供开关、异步构建、SSE 进度、Shadow mode 与自动回退。
- **Phase 3（扩展与优化）**：扩展到第二个知识库、实现增量更新、增加监控、输出推广决策报告。

本报告汇总三阶段数据，评估准确率提升、耗时开销、运营成本与风险，给出是否全面推广 GraphRAG 的明确建议。

---

## 2. 数据汇总

### 2.1 Phase 1：概念验证（PoC）

数据来源：`_bmad-output/specs/spec-cloudbrief-graphrag/poc-report.json`

| 指标 | 向量 RAG（Baseline） | 向量 RAG + GraphRAG |
|---|---|---|
| 测试问题数 | 15 | 15 |
| 正确数 | 14 | 13 |
| 准确率 | **93.33%** | **86.67%** |
| 平均延迟 | 9,379 ms | 19,282 ms |
| 抽取 overhead | — | 约 8,047 ms |
| 延迟 overhead 比例 | — | 105.58% |

**关键观察**：
- PoC 中 GraphRAG 准确率略低于向量 RAG，主要原因包括：
  - 部分问题（如“王建国向谁汇报？”）本身在文档中没有明确答案，baseline 和 GraphRAG 都未能正确回答。
  - GraphRAG 注入的子图上下文过大（20 个实体、47 个关系），可能干扰了 LLM 对核心事实的判断。
- GraphRAG 平均延迟约为 baseline 的 2 倍， overhead 主要来自 Neo4j 子图查询与 LLM 处理更长 prompt。

### 2.2 Phase 2：工程 MVP

Phase 2 重点在于工程落地，未单独跑 gold set 评估。完成度：

| 能力 | 状态 |
|---|---|
| 知识库级开关与 schema 配置 | ✅ 已完成 |
| schema 自动推荐 | ✅ 已完成 |
| Celery 异步图索引构建 | ✅ 已完成 |
| SSE 实时进度推送 | ✅ 已完成 |
| GenerationPipeline 集成与自动回退 | ✅ 已完成 |
| Shadow mode 数据收集 | ✅ 已完成（但尚无真实 query 日志） |
| 管理后台 UI | ✅ 已完成 |
| 单元/集成测试 | ✅ 部分完成 |

**Shadow mode 现状**：截至报告日，`graph_shadow_records` 表记录数为 0，暂无真实用户 query 日志可用于触发率/回退率分析。原因：
- Phase 2 期间未将 GraphRAG 开放给真实用户；
- Shadow mode 需管理员在后台显式开启，且默认关闭。

### 2.3 Phase 3：第二个知识库试点

数据来源：
- `backend/data/second_kb_pilot_report_8.json`
- `backend/data/second_kb_pilot_recall_report_8.json`

**试点知识库**：`GraphRAG 试点 - 供应链`（目录 ID: 8）  
**文档**：`graphrag_pilot_supply_chain.md`（约 4.3 KB）  
**Schema**：自动推荐 5 类实体（人员、部门、产品、供应商、项目）与 5 类关系（汇报给、负责、参与、依赖、协作）。

| 指标 | 向量 RAG | GraphRAG | 备注 |
|---|---|---|---|
| 实体召回 | 80.00% | 80.00% | 基于 gold set 字符串匹配 |
| 关系召回 | 45.00% | 55.00% | 基于 gold set 字符串匹配 |
| 子图实体召回 | — | 100.00% | 直接查询 Neo4j |
| 子图关系召回 | — | 100.00% | 直接查询 Neo4j |
| 图索引实体数 | — | 22 | — |
| 图索引关系数 | — | 45 | — |

**关键观察**：
- 子图召回率达到 100%，说明图索引构建成功，且能覆盖 gold set 中的期望实体与关系。
- 端到端答案中的关系召回率仅 55%，说明：
  - LLM 生成答案时并未总是以 gold set 期望的方式显式表达关系；
  - 部分答案虽然内容正确，但字符串匹配标准较严（如要求同时出现 source 和 target）。
- GraphRAG 上下文对答案质量仍有正面作用：例如问题“知识库产品的技术负责人是谁？”GraphRAG 答案明确给出“CloudBrief 知识库（KB）产品的技术负责人是赵敏”，比向量 RAG 答案更完整。

### 2.4 Phase 3：增量更新性能

数据来源：`backend/scripts/benchmark_graph_incremental.py`

| 场景 | 耗时 | 比例 |
|---|---|---|
| 全量写入（500 实体、490 关系） | 2.435 s | 100% |
| 增量更新（删除 + 重写单个 doc） | 0.361 s | **14.83%** |

**结论**：增量更新时间远低于全量重建 20% 的目标，满足 Epic 3 验收标准。

---

## 3. 真实 Query 日志分析

当前 `graph_shadow_records` 表记录数为 **0**，无法基于真实用户 query 计算 GraphRAG 触发率、回退率与差异指标。

建议：若进入下一轮试点，应在 1–2 个真实业务知识库上开启 Shadow mode，收集至少 100 条 query 后再做触发率/回退率分析。

---

## 4. 运营成本估算

### 4.1 成本构成

GraphRAG 在现有向量 RAG 基础上新增以下成本：

1. **LLM 抽取成本**
   - 每次图索引构建/增量更新需按 chunk 分批调用 LLM 抽取实体与关系。
   - 以本次试点为例：约 30 个 chunk，抽取耗时约 4–6 分钟，token 消耗约 10,000–15,000 tokens。
   - 按 DashScope 定价估算：每 1,000 tokens 约 ¥0.02–0.12（依模型），单个文档抽取成本约 ¥0.2–1.8。

2. **Neo4j 存储与计算成本**
   - 本地开发使用 Neo4j 5 Community，无额外许可费用。
   - 生产部署需考虑服务器资源：单个 10k 实体/20k 关系的图约占用 100–300 MB 存储，查询内存占用取决于并发量。

3. **增量维护成本**
   - 单文件增量更新耗时约为全量重建的 15%，对应成本也显著降低。
   - 频繁上传场景下，增量更新可避免重复抽取旧文档。

4. **监控与运维成本**
   - 已接入结构化日志监控慢查询、抽取质量、图谱新鲜度；
   - 生产环境如需持久化指标，建议引入 Prometheus/Grafana，增加少量运维投入。

### 4.2 规模估算

| 规模 | 文档数 | Chunk 数 | 预估全量建图 LLM 成本 | 预估 Neo4j 存储 |
|---|---|---|---|---|
| 小型 KB | 10 | 300 | ¥6–54 | < 100 MB |
| 中型 KB | 100 | 3,000 | ¥60–540 | 100–500 MB |
| 大型 KB | 1,000 | 30,000 | ¥600–5,400 | 500 MB–2 GB |

> 注：以上成本为单次全量抽取估算。实际成本受 schema 复杂度、chunk 大小、LLM 模型选择影响较大。

---

## 5. 风险与缓解

| 风险 | 影响 | 缓解措施 |
|---|---|---|
| **抽取质量不稳定** | 高 | 限定 schema、gold set 人工标注、持续评估；必要时引入 spaCy 依存解析降低 LLM 成本。 |
| **LLM / reranker API 稳定性不足** | 高 | 生产环境保留向量 RAG 自动回退；考虑本地部署 reranker 与 LLM。 |
| **子图上下文过大干扰答案** | 中 | 限制 max_hops 与 max_nodes；增加子图相关性过滤。 |
| **实体链接准确率影响 GraphRAG 触发** | 中 | 优化 entity link prompt；增加关键词/别名 fallback。 |
| **成本随知识库规模线性增长** | 中 | 使用增量更新避免重复抽取；按 KB 按需启用。 |
| **跨知识库数据隔离** | 高 | 所有 Cypher 查询强制 `kb_id` 过滤；定期审计。 |

---

## 6. 建议与下一步行动

### 6.1 总体建议：继续试点，暂不全面推广

理由：
1. 当前端到端准确率数据未能证明 GraphRAG 显著优于向量 RAG（PoC 甚至略低）。
2. 第二个知识库试点证明子图召回能力优秀（100%），但 LLM 生成阶段尚未充分利用图谱关系。
3. 无真实用户 query 日志，无法评估 Shadow mode 下的实际影响。
4. DashScope API 稳定性（reranker 返回空、LLM 超时）对生产环境构成风险。

### 6.2 下一步行动计划

1. **短期（1–2 周）**
   - 修复 `GraphRAGContextStage` 实体链接稳定性问题：当 LLM 链接失败时，使用图中实体名/别名做关键词 fallback。
   - 优化子图上下文：限制返回节点数，优先返回与问题最相关的路径。
   - 解决 reranker 可用性问题：验证本地 reranker 服务或切换更稳定的远程服务。

2. **中期（2–4 周）**
   - 在 1–2 个真实业务知识库上开启 Shadow mode，收集至少 100 条 query。
   - 基于真实 query 日志分析 GraphRAG 触发率、回退率与答案差异。
   - 重新评估关系型问题准确率，目标达到 ≥ 75%。

3. **长期（1–2 个月）**
   - 若 Shadow mode 数据显示 GraphRAG 在特定场景（组织架构、供应链、项目协作）准确率提升 ≥ 10% 且 overhead 可接受，则按场景分批次推广。
   - 对不适用的知识库（如纯概念知识点、退款政策等）保持 GraphRAG 关闭。

### 6.3 推广决策树

```
该知识库是否包含大量关系型信息？
├── 否 → 不建议启用 GraphRAG
└── 是 → 是否符合以下场景？
    ├── 组织架构 / 高管履历
    ├── 供应链 / 供应商关系
    ├── 项目协作 / 跨部门关系
    └── 产品-技术-依赖关系
        ├── 是 → 启用 GraphRAG，先 Shadow mode 观察
        └── 否 → 继续评估后再决定
```

---

## 7. 结论

GraphRAG 在工程上已具备可运行、可监控、可回退的能力，子图召回效果良好，增量更新性能达标。但在当前数据下，尚未形成对向量 RAG 的显著端到端准确率优势，且外部 API 稳定性存在生产风险。

**建议继续试点，聚焦实体链接优化、Shadow mode 数据收集与真实场景验证，待数据支撑后再决定是否全面推广。**
