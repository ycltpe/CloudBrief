---
stepsCompleted:
  - validate-prerequisites
  - extract-requirements
  - design-epics
  - write-stories
inputDocuments:
  - ../specs/spec-cloudbrief-graphrag/SPEC.md
  - ../specs/spec-cloudbrief-graphrag/stack.md
  - ../specs/spec-cloudbrief-graphrag/schema-definitions.md
  - ../specs/spec-cloudbrief-graphrag/architecture-diagrams.md
  - ../specs/spec-cloudbrief-graphrag/implementation-roadmap.md
updated: 2026-07-09
---

# CloudBrief GraphRAG - Epic & Story 分解

## 需求清单

### 功能需求

FR1: 管理员可按知识库启用/关闭 GraphRAG。
FR2: 系统可为每个知识库自动生成并推荐实体/关系 schema，管理员可确认或微调。
FR3: 系统可从已索引的文本 chunks 中抽取实体与关系。
FR4: 系统可将抽取结果异步写入 Neo4j 图数据库，并按 `kb_id` 隔离。
FR5: 系统可在 LLM 生成阶段注入与问题相关的图谱上下文。
FR6: 系统可复用现有 Celery + Redis Pub/Sub + SSE 机制推送图谱构建进度。
FR7: 管理后台提供 GraphRAG 配置界面与构建任务状态展示。
FR8: 当图谱不可用、查询无法映射到图或 GraphRAG 阶段异常时，系统自动回退到向量 RAG。
FR9: Phase 2 启用 shadow mode，同时运行 GraphRAG 但不影响最终答案，仅记录差异。

### 非功能需求

NFR1: 所有 Cypher 查询必须参数化，禁止字符串拼接。
NFR2: `kb_id` 必须作为每个图查询的强制过滤参数。
NFR3: GraphRAG 默认对所有知识库关闭。
NFR4: 禁止修改现有 `RetrievalPipeline` 与 `GenerationPipeline` 的默认行为。
NFR5: 不引入新的微服务，所有模块运行在现有 FastAPI + Celery 进程中。
NFR6: 新增依赖使用 `backend/pyproject.toml` 的 `[project.optional-dependencies] graphrag` 组。
NFR7: GraphRAG 阶段额外耗时不超过向量 RAG 总耗时的 30%。
NFR8: 构建成功率 ≥ 95%。

### 其他技术要求

- Docker Compose 新增 Neo4j 5 Community 服务。
- FastAPI lifespan 初始化 `GraphStore`。
- 新增模块：`app/stores/graph_store.py`、`app/services/graph_extraction.py`、`app/stages/graph_rag_context_stage.py`、`app/tasks/graph_indexing.py`、`app/models/graph_schemas.py`。
- 扩展 `app/models/schemas.py` 增加 GraphRAG 相关 DTO。
- 扩展 SSE 事件类型：`graph_extraction`、`graph_building`、`graph_indexing_complete`。
- 前端管理后台在知识库页面增加 GraphRAG 配置卡片。

## Epic 1：GraphRAG 概念验证（Phase 1）

**目标：** 验证抽取质量、生成阶段增强效果以及用户侧开关+场景提示的产品可用性，产出技术与产品两方面的评估报告。

### Story 1.1：搭建 Neo4j 开发环境

As a 后端开发，
I want 在本地 Docker Compose 中启动 Neo4j 5 Community，
So that 团队可以在统一环境中开发 GraphRAG 功能。

**Acceptance Criteria:**

**Given** 开发者已克隆仓库
**When** 执行 `docker compose up -d`
**Then** Neo4j Bolt 端口 7687 与 Browser 端口 7474 可用
**And** 应用可通过 `NEO4J_URI`/`NEO4J_USER`/`NEO4J_PASSWORD` 连接

### Story 1.2：实现最小可用 GraphStore

As a 后端开发，
I want 封装 Neo4j 异步驱动的增删改查接口，
So that 上层服务可以按知识库隔离地读写图谱。

**Acceptance Criteria:**

**Given** `GraphStore` 已初始化
**When** 调用 `upsert_entities`、`upsert_relations`、`get_subgraph_context`
**Then** 数据按 `kb_id` 写入 Neo4j
**And** 查询其他 `kb_id` 时返回空结果
**And** 所有 Cypher 查询均为参数化查询

### Story 1.3：实现 GraphExtractionService

As a 后端开发，
I want 基于 LLM 从 chunks 中抽取符合 schema 的实体与关系，
So that 图谱构建有结构化输入。

**Acceptance Criteria:**

**Given** 一组已切分的 chunks 和一份 schema
**When** 调用抽取服务
**Then** 输出 JSON 格式的实体/关系列表
**And** 实体准确率 ≥ 80%（人工抽样 50 条）
**And** 关系准确率 ≥ 70%（人工抽样 50 条）

### Story 1.4：实现 GraphRAGContextStage

As a 后端开发，
I want 在生成阶段注入文本化子图上下文，
So that LLM 能利用关系路径回答跨实体问题。

**Acceptance Criteria:**

**Given** 一个问题、检索到的 chunks、以及对应知识库的 Neo4j 子图
**When** 调用 `GraphRAGContextStage`
**Then** 生成包含实体关系路径的 prompt 片段
**And** 不修改 `RetrievalPipeline` 的输入输出

### Story 1.5：构建 gold set 并评估 PoC

As a 算法工程师，
I want 准备 20–50 个关系型问题并对比向量 RAG vs 向量 RAG + GraphRAG，
So that 证明 GraphRAG 在关系型问题上的价值。

**Acceptance Criteria:**

**Given** 测试人员已在某个适合 GraphRAG 的知识库上启用并构建图索引
**When** 在 gold set 上运行评估脚本
**Then** 输出子图召回率、关系型问题准确率、耗时对比
**And** 关系型问题准确率 ≥ 75%
**And** GraphRAG 额外耗时 ≤ 向量 RAG 30%

## Epic 2：GraphRAG 工程 MVP（Phase 2）

**目标：** 将 GraphRAG 集成到 CloudBrief 主流程，实现可演示的端到端能力。

### Story 2.1：知识库级 GraphRAG 开关与 Schema 配置

As a 系统管理员，
I want 在创建新知识库或管理后台按知识库启用/关闭 GraphRAG 并编辑实体/关系 schema，
So that 我可以控制哪些知识库使用 GraphRAG。

**Acceptance Criteria:**

**Given** 管理员正在创建新知识库
**When** 在创建弹窗/页面中查看 GraphRAG 选项
**Then** 开关默认关闭，开关旁显示场景提示
**And** 保存后配置持久化到 MySQL `kb_graph_schemas`

**Given** 管理员已登录后台并进入知识库管理页
**When** 切换 GraphRAG 开关并保存 schema
**Then** 配置持久化到 MySQL `kb_graph_schemas`
**And** 系统可基于 chunks 采样自动生成 schema 推荐供管理员确认
**And** 未启用 GraphRAG 的知识库问答流程保持不变

### Story 2.2：Celery 异步图谱构建任务

As a 系统管理员，
I want 触发图谱重建或上传新文档后由 Celery 异步执行图索引构建，
So that 构建过程不阻塞前端。

**Acceptance Criteria:**

**Given** 管理员点击「重建图谱」
**When** 后端提交 `rebuild_graph_task` 到 Celery
**Then** Worker 按 chunks → 抽取 → 写入 Neo4j 的顺序执行
**And** 每阶段通过 Redis Pub/Sub 发布进度事件
**And** 构建失败时记录错误并允许重试

**Given** 某知识库已启用 GraphRAG 且上传了新文档
**When** 单文件向量索引任务完成
**Then** 系统自动触发该文档的图索引抽取任务（Phase 2 可先全量重建，Phase 3 改为增量更新）
**And** 上传任务的事件流或子任务事件流中展示 `graph_extraction`、`graph_building`、`graph_indexing_complete` 阶段

### Story 2.3：SSE 进度推送给前端

As a 系统管理员，
I want 在前端看到图谱构建的实时进度，
So that 了解构建状态。

**Acceptance Criteria:**

**Given** 图谱构建任务已启动
**When** 前端连接 `/index/tasks/{task_id}/events`
**Then** 收到 `graph_extraction`、`graph_building`、`graph_indexing_complete` 事件
**And** 进度从 0 到 1 连续更新

### Story 2.4：GenerationPipeline 集成与回退

As a 后端开发，
I want `GenerationPipeline` 在启用 GraphRAG 时注入图谱上下文并在异常时回退，
So that 系统稳定运行。

**Acceptance Criteria:**

**Given** 知识库开启 GraphRAG
**When** 问答流程到达生成阶段
**Then** `GraphRAGContextStage` 在 `GenerationLLMStage` 前注入子图上下文
**And** 若 Neo4j 不可用、schema 为空或阶段抛异常，自动跳过 GraphRAG
**And** 最终答案仍基于现有向量 RAG 链路

### Story 2.5：Shadow Mode 数据收集

As a 产品经理，
I want Phase 2 同时运行 GraphRAG 但不影响最终答案，
So that 可以安全评估 GraphRAG 对真实查询的影响。

**Acceptance Criteria:**

**Given** Shadow mode 已开启
**When** 真实用户提问
**Then** 系统仍返回向量 RAG 答案
**And** 同时记录 GraphRAG 生成的候选答案、子图上下文与差异指标
**And** 后台可查看 shadow mode 对比报告

### Story 2.6：管理后台 GraphRAG UI

As a 前端开发，
I want 在知识库管理页增加 GraphRAG 配置卡片，
So that 管理员可以可视化配置。

**Acceptance Criteria:**

**Given** 管理员进入知识库管理页
**When** 展开 GraphRAG 卡片
**Then** 可开关 GraphRAG、查看/编辑 schema、触发重建、查看最近任务状态
**And** UI 同时支持明亮与暗黑模式

### Story 2.7：创建知识库时的 GraphRAG 场景引导

As a 系统管理员，
I want 在创建新知识库时看到 GraphRAG 开关及场景提示，
So that 我能判断当前知识库是否适合启用 GraphRAG。

**Acceptance Criteria:**

**Given** 管理员点击"创建知识库"
**When** 创建弹窗/页面渲染
**Then** GraphRAG 开关默认关闭
**And** 开关附近显示场景提示，说明适合与不适合的场景

**Given** 管理员将鼠标悬停或点击场景提示旁的"?"图标
**When** 展开详细说明
**Then** 显示至少 3 个适合场景示例和 2 个不适合场景示例

**Given** 管理员关闭 GraphRAG 开关
**When** 保存知识库
**Then** 该知识库问答流程与改造前完全一致

**Given** 管理员开启 GraphRAG 开关
**When** 保存知识库
**Then** 系统提示"保存后可在知识库设置页配置 schema 并触发图谱构建"
**And** 后端为该知识库创建默认关闭的 GraphRAG 配置记录

## Epic 3：GraphRAG 扩展与优化（Phase 3）

**目标：** 评估 ROI，扩展至第二个知识库，完善增量更新与监控。

> 详细任务拆分、依赖关系、验收标准与风险缓解见：
> `_bmad-output/specs/spec-cloudbrief-graphrag/epic3-breakdown.md`

### Story 3.1：第二个知识库试点

As a 产品经理，
I want 将 GraphRAG 扩展到第二个知识库并复用相同评估流程，
So that 验证方案的通用性。

**Acceptance Criteria:**

**Given** 第二个知识库已完成向量索引
**When** 启用 GraphRAG 并运行 gold set 评估
**Then** 关系型问题准确率 ≥ 75%
**And** 子图召回率 ≥ 75%

**子任务：**

- **Task 3.1.1** 选择第二个试点知识库并记录场景/文档类型/chunk 数量。
- **Task 3.1.2** 为第二个知识库生成并确认 schema（entity_types / relation_types）。
- **Task 3.1.3** 执行第二个知识库的全量图索引构建（验证 Celery + SSE 全链路）。
- **Task 3.1.4** 准备第二个知识库的 gold set（20–30 条关系型问题）。
- **Task 3.1.5** 运行「纯向量 RAG」vs「向量 RAG + GraphRAG」对比评估。
- **Task 3.1.6** 输出第二个知识库试点评估报告。

### Story 3.2：图谱增量更新

As a 后端开发，
I want 单文件上传后只更新该文件相关的图谱子集，
So that 避免每次全量重建。

**Acceptance Criteria:**

**Given** 知识库已启用 GraphRAG 且上传新文件
**When** 单文件向量索引任务完成并触发图索引增量更新任务
**Then** 仅抽取并写入新文件相关的实体/关系，并删除该文件旧版本产生的实体/关系（如有）
**And** 增量更新时间 ≤ 全量重建时间的 20%
**And** 上传任务的事件流或子任务事件流中展示增量图更新阶段

**子任务：**

- **Task 3.2.1** 设计按 `doc_id` / `chunk_id` 标记的实体/关系删除策略。
- **Task 3.2.2** 扩展 `GraphStore` 支持按 `doc_id` 删除实体/关系（Cypher 参数化 + `kb_id` 过滤）。
- **Task 3.2.3** 修改图索引任务支持增量模式（删除旧数据 → 抽取新数据 → 写入）。
- **Task 3.2.4** 在单文件向量索引完成后自动触发增量图更新任务。
- **Task 3.2.5** 确保增量图更新任务发布 `graph_extraction`、`graph_building`、`graph_indexing_complete` SSE 事件。
- **Task 3.2.6** 对比增量更新与全量重建耗时，验证 ≤ 20%。

### Story 3.3：性能与成本监控

As a 运维工程师，
I want 监控 Neo4j 查询性能、抽取质量与图谱新鲜度，
So that 及时发现并优化瓶颈。

**Acceptance Criteria:**

**Given** GraphRAG 已上线
**When** 查看监控看板
**Then** 可看到平均查询耗时、抽取准确率趋势、图谱最后更新时间
**And** 关键指标异常时可有日志告警

**子任务：**

- **Task 3.3.1** 增加 Neo4j 查询耗时监控（`get_subgraph_context`、增删改等关键操作）。
- **Task 3.3.2** 增加抽取质量监控（基于 gold set / 抽样的准确率趋势）。
- **Task 3.3.3** 增加图谱新鲜度监控（每个 KB 最后图索引更新时间）。
- **Task 3.3.4** 在 admin dashboard 增加 GraphRAG 监控卡片（明亮/暗黑模式）。
- **Task 3.3.5** 配置关键指标异常日志告警（阈值可配置）。

### Story 3.4：推广决策报告

As a 项目负责人，
I want 基于 gold set 与真实 query 日志输出推广决策报告，
So that 决定是否全面引入 GraphRAG。

**Acceptance Criteria:**

**Given** Phase 1/2/3 数据已收集
**When** 生成决策报告
**Then** 报告包含准确率提升、耗时开销、成本估算、风险与建议
**And** 明确给出全面推广/继续试点/暂停的建议

**子任务：**

- **Task 3.4.1** 收集 Phase 1/2/3 评估数据。
- **Task 3.4.2** 基于真实 query 日志分析 GraphRAG 触发率与回退率。
- **Task 3.4.3** 估算 GraphRAG 运营成本（LLM、Neo4j、存储、Worker 资源）。
- **Task 3.4.4** 编写推广决策报告（准确率、耗时、成本、风险、建议）。
- **Task 3.4.5** 明确给出「全面推广 / 继续试点 / 暂停」建议及下一步行动计划。

## 需求覆盖矩阵

| 功能需求 | Epic 1 | Epic 2 | Epic 3 |
|---|---|---|---|
| FR1 按 KB 开关 | - | Story 2.1 | - |
| FR2 schema 自动生成 | Story 1.3 | Story 2.1 | - |
| FR3 实体/关系抽取 | Story 1.3 | Story 2.2 | - |
| FR4 写入 Neo4j | Story 1.2 | Story 2.2 | Story 3.2 |
| FR5 生成阶段注入 | Story 1.4 | Story 2.4 | - |
| FR6 SSE 进度推送 | - | Story 2.3 | - |
| FR7 管理后台 UI | - | Story 2.6 | - |
| FR8 自动回退 | Story 1.4 | Story 2.4 | - |
| FR9 Shadow mode | - | Story 2.5 | - |
