# 实施路线图

## Phase 1：概念验证（2 周）

**目标**：验证抽取质量、生成阶段增强效果，以及 schema 自动生成在不同场景样本上的稳定性。

**交付物**：
1. 本地 Neo4j 容器 + 2–3 个典型场景样本知识库（组织架构、高管履历、供应链）的端到端 GraphRAG 链路。
2. 按场景划分的 30–50 个关系型问题 gold set。
3. 抽取准确率、子图召回率、关系型问题准确率、耗时评估报告。
4. 创建/配置知识库时的 GraphRAG 开关 + 场景提示文案初稿（用于 Phase 2 UI）。

**核心任务**：
- 搭建 Neo4j 5 Community 开发环境（Docker Compose）。
- 实现最小可用 `GraphStore`、`GraphExtractionService`、`GraphRAGContextStage`。
- 编写独立脚本 `scripts/build_graph_poc.py`，无需 Celery 即可快速验证。
- 定义跨场景通用 schema 模板与自动推荐逻辑。
- 选取/构造 2–3 个代表性样本知识库（组织架构、高管履历、供应链文档）。
- 在 gold set 上对比向量 RAG vs 向量 RAG + GraphRAG 上下文。

**验收标准**：
- 实体抽取准确率 ≥ 80%。
- 关系抽取准确率 ≥ 70%。
- 关系型问题准确率 ≥ 75%。
- 额外耗时 ≤ 向量 RAG 30%。
- schema 自动推荐在 2 个以上场景可用。

## Phase 2：工程 MVP（4–6 周）

**目标**：将 GraphRAG 集成到 CloudBrief 主流程，实现用户可在创建/配置知识库时自助启用并获得场景提示的端到端能力。

**交付物**：
1. 知识库级 GraphRAG 开关与 schema 配置（创建知识库流程 + 管理后台）。
2. GraphRAG 场景提示组件与文案（支持明亮/暗黑模式）。
3. Celery 异步图谱构建任务 + Redis Pub/Sub + SSE 进度推送（覆盖「重建图谱」与「上传文档后自动触发」两种流程）。
4. `GenerationPipeline` 集成与自动回退机制。
5. Shadow mode 数据收集与对比报告。
6. 单元测试与集成测试覆盖核心路径。
7. 管理后台 UI 支持开启/关闭、schema 编辑、触发重建、查看状态。

**核心任务**：
- 扩展 `app/config.py` 增加 Neo4j 配置。
- 在 FastAPI `lifespan` 中初始化 `GraphStore`。
- 新增 `app/stores/graph_store.py`、`app/services/graph_extraction.py`、`app/stages/graph_rag_context_stage.py`、`app/tasks/graph_indexing.py`、`app/models/graph_schemas.py`。
- 扩展 `app/models/schemas.py` 增加 GraphRAG 相关 DTO，并在创建知识库 DTO 中增加 `enable_graph_rag` 字段。
- 扩展创建知识库 API，默认写入 `kb_graph_schemas` 配置行。
- 新增 admin API：`PUT /admin/kbs/{kb_id}/graph-rag-config`、`POST /index/{kb_id}/rebuild-graph`。
- 扩展 SSE 事件类型：`graph_extraction`、`graph_building`、`graph_indexing_complete`。
- 前端在创建知识库弹窗/页面增加 GraphRAG 开关与场景提示。
- 前端在 `app/admin/kb` 页面增加 GraphRAG 配置卡片。

**验收标准**：
- 构建成功率 ≥ 95%。
- 创建知识库流程与管理后台均可完成开关、schema 编辑、触发重建、查看状态全链路。
- GraphRAG 阶段异常时系统仍返回向量 RAG 答案。
- Shadow mode 可记录差异并生成对比报告。

## Phase 3：扩展与优化（2–4 周）

**目标**：按场景评估 ROI，完善增量更新与监控，给出分场景推广建议。

**交付物**：
1. 多场景泛化验证报告（在非样本知识库上测试 schema 自动生成与抽取）。
2. 图谱增量更新机制（单文件/单 chunk 更新）。
3. 性能监控与成本看板（按场景/按知识库维度）。
4. 分场景推广决策报告（哪些场景适合开，哪些不建议）。

**核心任务**：
- 在 2–3 个新场景知识库上做泛化验证。
- 实现单文件增量图谱更新（与向量索引增量更新对齐）。
- 引入 spaCy 依赖解析，降低 LLM 抽取成本。
- 增加 Neo4j 查询性能监控、抽取质量监控、图谱新鲜度监控。
- 根据 gold set 与真实 query 日志评估 ROI，按场景给出推广建议。

**验收标准**：
- 新场景知识库达到 Phase 1 同等准确率。
- 增量更新时间 ≤ 全量重建时间的 20%。
- 生成阶段 GraphRAG 开销 ≤ 向量 RAG 总耗时的 30%。
- 报告明确给出分场景推广建议。

## 依赖关系

```
Phase 1 ──→ Phase 2 ──→ Phase 3
   │           │           │
   └───────────┴───────────┘
        均需现有向量 RAG 链路作为回退
```

## 风险与缓解

| 风险 | 影响 | 缓解 |
|---|---|---|
| 抽取质量不稳定 | 高 | 限定 schema、人工标注 gold set、持续评估。 |
| 工程复杂度超预期 | 中 | 分阶段交付，保留向量 RAG 回退能力。 |
| 成本超预算 | 中 | PoC 后评估 ROI，必要时切换混合抽取。 |
| 跨知识库泄露 | 高 | `kb_id` 属性隔离 + 参数化查询 + 管理接口权限控制。 |
