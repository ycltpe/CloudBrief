# GraphRAG 实施任务清单

本文件将 SPEC 中的 capability 与路线图拆解为可执行、可追踪的工程师任务。每项任务建议包含负责人、估点与状态列，供冲刺规划直接使用。

## 图例

- `[ ]` 待办
- `[-]` 进行中
- `[x]` 已完成
- `[b]` 阻塞

## Phase 1：概念验证（2 周）

### 基础设施

- [ ] **TASK-1.1** 在 `docker-compose.yml` 新增 `neo4j:5-community` 服务（端口 7687/7474、数据卷持久化）
- [ ] **TASK-1.2** 在 `.env.example` 与 `app/config.py` 增加 Neo4j 配置项（`NEO4J_URI`、`NEO4J_USER`、`NEO4J_PASSWORD`）
- [ ] **TASK-1.3** 在 `backend/pyproject.toml` 新增 `[project.optional-dependencies] graphrag = ["neo4j>=5.20"]`
- [ ] **TASK-1.4** 在 FastAPI `lifespan` 中初始化 `AsyncGraphDatabase` driver，并在关闭时清理

### 核心模块

- [ ] **TASK-1.5** 创建 `app/stores/graph_store.py`：
  - 实现 `upsert_entities`、`upsert_relations`、`get_subgraph_context`
  - 所有 Cypher 参数化，强制过滤 `kb_id`
  - 创建唯一约束与索引
- [ ] **TASK-1.6** 创建 `app/models/graph_schemas.py`：
  - `EntityType`、`RelationType`、`KbGraphSchema`、`Entity`、`Relation`
- [ ] **TASK-1.7** 创建 `app/services/graph_extraction.py`：
  - LLM prompt 模板与抽取输出 schema
  - 输入 chunks，输出 `list[Entity]` / `list[Relation]`
  - 人工抽样评估接口
- [ ] **TASK-1.8** 创建 `app/stages/graph_rag_context_stage.py`：
  - 从问题中识别实体
  - 调用 `GraphStore.get_subgraph_context`（1–2 跳）
  - 将子图文本化并注入 prompt
- [ ] **TASK-1.9** 创建 `scripts/build_graph_poc.py`：
  - 独立运行，无需 Celery
  - 支持从试点知识库 chunks 构建图并评估

### 评估

- [ ] **TASK-1.10** 准备 2–3 个典型场景样本知识库（组织架构、高管履历、供应链）并准备 20–50 条关系型问题 gold set
- [ ] **TASK-1.11** 运行向量 RAG vs 向量 RAG + GraphRAG 对比评估
- [ ] **TASK-1.12** 输出 PoC 评估报告（准确率、召回率、耗时、成本）

## Phase 2：工程 MVP（4–6 周）

### 配置与数据持久化

- [ ] **TASK-2.1** 新增 MySQL 表 `kb_graph_schemas` 与 `kb_graph_build_tasks`：
  - `kb_graph_schemas` 增加 `enabled`（bool，默认 false）、`enabled_by_user`（bool）、`enabled_at`（datetime）字段，记录用户主动启用时间
  - 创建知识库时自动写入默认 `enabled=false` 的配置行
- [ ] **TASK-2.2** 扩展 `app/models/schemas.py` 增加 GraphRAG DTO
- [ ] **TASK-2.3** 实现 schema 自动生成/推荐：
  - 基于 chunks 采样调用 LLM 推荐 entity_types / relation_types
  - 管理员可一键确认或微调
- [ ] **TASK-2.4** 新增 admin API `PUT /admin/kbs/{kb_id}/graph-rag-config`：支持更新开关状态与 schema，同步更新 `enabled_by_user`/`enabled_at`
- [ ] **TASK-2.5** 新增 admin API `GET /admin/kbs/{kb_id}/graph-rag-config`：返回开关状态、schema、自动生成推荐与最近任务状态

### 异步构建与事件

- [ ] **TASK-2.6** 创建 `app/tasks/graph_indexing.py`：
  - `rebuild_graph_task`：全量重建某知识库的图索引
  - `index_file_graph_task`：单文件索引完成后，若 KB 启用 GraphRAG 则触发该文件的图索引抽取/写入
  - 在 `index_file_task` 或 `IndexService` 中增加钩子，向量索引完成后根据 `kb_graph_schemas.enabled` 自动触发图索引任务
- [ ] **TASK-2.7** 在 `IndexService` 中新增触发图谱重建的方法
- [ ] **TASK-2.8** 扩展 SSE 事件类型：
  - 新增 `graph_extraction`、`graph_building`、`graph_indexing_complete`
  - 确保这些事件在「重建图谱」任务和「上传文档后的单文件索引任务」两种流程中均能发布
  - `useTaskStream` hook 能正确识别并展示 graph 相关 stage
- [ ] **TASK-2.9** 新增 API `POST /index/{kb_id}/rebuild-graph`
- [ ] **TASK-2.10** 确保 Celery Worker 监听图谱任务队列

### 生成阶段集成

- [ ] **TASK-2.11** 修改 `GenerationPipeline` 注入 `GraphRAGContextStage`
- [ ] **TASK-2.12** 实现回退逻辑：
  - Neo4j 不可用 → 跳过
  - schema 为空 → 跳过
  - 未识别实体 → 跳过
  - 阶段抛异常 → 记录日志并跳过
- [ ] **TASK-2.13** 实现 Shadow mode：
  - 配置项 `shadow_mode_enabled`
  - 同时调用 GraphRAG 但不影响最终答案
  - 记录候选答案、子图上下文、差异指标

### 前端

- [ ] **TASK-2.14** 扩展 `useTaskStream` hook 识别 graph 相关 stage
- [ ] **TASK-2.15** 在创建知识库弹窗/页面和 `app/admin/kb` 页面新增 GraphRAG 配置卡片：
  - 开关（默认关闭）
  - schema 编辑器（JSON / 表格式，仅设置页）
  - 自动生成 schema 按钮（仅设置页）
  - 重建图谱按钮（仅设置页）
  - 最近任务状态
- [ ] **TASK-2.16** 确保新增 UI 同时支持明亮/暗黑模式

### 测试

- [ ] **TASK-2.17** 单元测试：`GraphStore` 参数化查询、`GraphExtractionService` 输出格式
- [ ] **TASK-2.18** 集成测试：图谱构建 → SSE 进度 → 生成阶段注入端到端
- [ ] **TASK-2.19** 异常回退测试：Neo4j 断开时仍返回向量 RAG 答案
- [ ] **TASK-2.20** 设计并实现 GraphRAG 场景提示组件：
  - 在 `frontend/components/` 下新增 `GraphRagHint` 组件
  - 支持 `compact`（创建弹窗内联）和 `expanded`（设置页/Tooltip 详细）两种模式
  - 文案需经产品确认，组件需同时支持明亮/暗黑模式
  - 包含"?"图标 + Tooltip/Popover 交互
- [ ] **TASK-2.21** 扩展创建知识库 API 以支持 GraphRAG 默认配置：
  - 创建知识库时同步写入 `kb_graph_schemas` 默认行，`enabled=false`
  - 若前端传递 `enable_graph_rag=true`，则写入 `enabled=true` 并记录 `enabled_by_user`/`enabled_at`
- [ ] **TASK-2.22** 前端可用性验证（可选，建议 Phase 2 末期做）：
  - 邀请 3–5 位内部用户完成"创建知识库并决定是否启用 GraphRAG"任务
  - 记录理解耗时、误开启率、误关闭率，输出 1 页结论

## Phase 3：扩展与优化（2–4 周）

### 增量更新

- [ ] **TASK-3.1** 设计按 `doc_id` / `chunk_id` 标记的实体/关系删除策略
- [ ] **TASK-3.2** 实现单文件增量图谱更新任务：
  - 在单文件向量索引任务完成后，若 KB 启用 GraphRAG 则自动触发
  - 仅抽取并写入新文件相关实体/关系，并删除该文件旧版本产生的图数据
  - 在同一事件流或子任务事件流中发布 `graph_extraction`、`graph_building`、`graph_indexing_complete` 阶段事件
- [ ] **TASK-3.3** 对比增量更新与全量重建耗时，验证 ≤ 20%

### 性能与成本

- [ ] **TASK-3.4** 引入 spaCy 依存解析，降低 LLM 抽取成本
- [ ] **TASK-3.5** 增加 Neo4j 查询耗时监控
- [ ] **TASK-3.6** 增加抽取质量监控（准确率趋势）
- [ ] **TASK-3.7** 增加图谱新鲜度监控（最后更新时间）

### 推广评估

- [ ] **TASK-3.8** 第二个知识库 GraphRAG 试点与评估
- [ ] **TASK-3.9** 基于 gold set 与真实 query 日志评估 ROI
- [ ] **TASK-3.10** 输出推广决策报告

## 依赖关系

```
Phase 1 任务 1.1–1.4 → 任务 1.5–1.9 → 任务 1.10–1.12
Phase 2 任务 2.1–2.5 → 任务 2.6–2.13 → 任务 2.14–2.19
Phase 3 任务 3.1–3.10
```

## 风险项

| 风险 | 关联任务 | 缓解 |
|---|---|---|
| 抽取质量不稳定 | TASK-1.7、TASK-1.11 | 限定 schema、gold set 人工标注、持续评估 |
| 工程复杂度超预期 | TASK-2.11、TASK-2.12 | 分阶段交付，保留向量 RAG 回退 |
| 成本超预算 | TASK-1.7、TASK-3.4 | PoC 后评估 ROI，必要时切换混合抽取 |
| 跨知识库泄露 | TASK-1.5、TASK-2.4 | `kb_id` 属性隔离 + 参数化查询 + 权限控制 |
