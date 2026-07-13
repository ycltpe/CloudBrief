---
id: SPEC-cloudbrief-graphrag
companions:
  - stack.md
  - schema-definitions.md
  - architecture-diagrams.md
  - implementation-roadmap.md
sources:
  - ../../planning-artifacts/briefs/brief-knowledgeAgents-2026-07-08/brief.md
  - ../../planning-artifacts/research/technical-cloudbrief-graphrag-research-2026-07-08.md
---

> **Canonical contract.** This SPEC and the files in `companions:` are the complete, preservation-validated contract for what to build, test, and validate. Source documents listed in frontmatter are for traceability only.

# CloudBrief 按知识库选择性引入 GraphRAG

## Why

CloudBrief 现有向量 RAG 链路（BM25 + 向量 → RRF → Rerank → 引用生成）擅长回答段落级事实问题，但在跨文档实体关系、因果链、比较推理等问题上存在“找得到片段，拼不出关系”的瓶颈。企业用户需要回答“张三和李四是否在同一家子公司任过职”“某供应商的上游合作伙伴有哪些”这类问题，答案分散且依赖显式关系路径。本工作按知识库选择性引入 GraphRAG，在**不替换现有检索链路**的前提下，为关系型问题补充结构化图谱上下文，使 CloudBrief 从信息检索助手演进为企业知识推理助手。

## Capabilities

- **CAP-1**
  - **intent:** 管理员可以在创建或配置知识库时启用/关闭 GraphRAG，并为该知识库配置实体类型与关系类型 schema。
  - **success:** 在创建知识库目录或进入知识库设置页时，管理员可以看到默认关闭的 GraphRAG 开关；开启后配置即时持久化。仅当开关开启且 schema 非空时，该知识库的问答流程才会调用 GraphRAG。schema 可由系统基于 chunks 采样自动生成并推荐，管理员一键确认或微调后生效。未启用 GraphRAG 的知识库流程与改造前完全一致。

- **CAP-2**
  - **intent:** 系统能够从已索引的文本 chunks 中抽取实体与关系，供构建知识图谱使用。
  - **success:** 对试点知识库的 chunks 运行抽取后，输出符合 schema 的实体/关系 JSON，人工抽样验证实体准确率 ≥ 80%、关系准确率 ≥ 70%。

- **CAP-3**
  - **intent:** 系统能够将抽取结果异步写入 Neo4j 图数据库，并按知识库隔离。
  - **success:** 写入完成后，通过 Cypher 按 `kb_id` 查询可返回该知识库的全部实体与关系，且无法查询到其他知识库的图数据。

- **CAP-4**
  - **intent:** 系统能够在 LLM 生成阶段注入与问题相关的图谱上下文，且不改变现有检索链路行为。
  - **success:** 对启用 GraphRAG 的知识库，生成阶段 prompt 包含“检索 chunks + 文本化子图上下文”；对未启用的知识库，流程与改造前完全一致。

- **CAP-5**
  - **intent:** 系统能够复用现有 Celery + Redis Pub/Sub + SSE 机制推送图谱构建进度；在文档上传后的索引流程中，若知识库已启用 GraphRAG，则自动触发图索引构建/更新，并在同一事件流中展示。
  - **success:** 前端在 `/index/tasks/{task_id}/events` 可收到 `graph_extraction`、`graph_building`、`graph_indexing_complete` 阶段事件，进度从 0 到 1 连续更新；单文件上传任务完成后，若对应知识库启用 GraphRAG，系统能在同一任务事件流或子任务事件流中触发并展示图索引抽取与写入过程，无需管理员手动重建。

- **CAP-6**
  - **intent:** 管理后台提供 GraphRAG 配置界面与构建任务状态展示。
  - **success:** 管理员可在知识库管理页开启/关闭 GraphRAG、编辑 schema、触发图谱重建，并查看最近一次构建任务的状态与日志摘要。

- **CAP-7**
  - **intent:** 当图谱不可用、查询无法映射到图或 GraphRAG 阶段异常时，系统自动回退到向量 RAG。
  - **success:** 移除 Neo4j 连接、清空 schema、输入无实体问题或 GraphRAG 抛异常时，系统仍返回基于现有检索链路的答案，不报错且无结果质量退化。

- **CAP-8**
  - **intent:** 在创建或配置知识库时，系统向用户展示 GraphRAG 开关，并在开关附近提供场景提示，明确说明 GraphRAG 适合哪些类型的问题与知识库内容。
  - **success:** 开关默认关闭，用户显式开启后配置即时持久化。创建/配置知识库时，管理员能在 30 秒内理解开关含义。开关旁展示的场景提示包含至少 3 个适合场景与 2 个不适合场景。开启后该知识库的问答流程正确调用 GraphRAG；关闭后流程与改造前完全一致。

## Constraints

- 禁止修改现有 `RetrievalPipeline` 与 `GenerationPipeline` 的默认行为；GraphRAG 必须是可开关、可移除的可插拔阶段。
- 所有 Cypher 查询必须参数化，禁止字符串拼接；`kb_id` 必须作为每个查询的强制过滤参数。
- GraphRAG 对所有知识库默认关闭，启用需管理员显式配置。
- 不引入新的微服务；所有 GraphRAG 模块运行在现有 FastAPI 应用与 Celery Worker 进程中。
- 新增依赖使用 `backend/pyproject.toml` 的 `[project.optional-dependencies] graphrag` 组，避免默认安装增重。
- GraphRAG 开关在所有创建/配置入口默认关闭，必须用户显式开启后方可生效；创建时只做开关选择，schema 配置与图谱重建在后续步骤完成。

## Non-goals

- MVP 不支持跨知识库统一大图。
- MVP 不支持全自动、零监督的通用图谱构建。
- MVP 不支持复杂多跳 Agent 推理（仅支持 1–2 跳子图检索）。
- MVP 不要求实时图谱更新；分钟/小时级延迟可接受。

## Success signal

在至少一个由用户主动启用 GraphRAG 的知识库上，使用 20–50 个人工标注的关系型问题 gold set 评估：子图召回率 ≥ 75%（关键实体/关系被包含）、关系型问题回答准确率 ≥ 75%；GraphRAG 阶段带来的额外耗时不超过向量 RAG 链路总耗时的 30%；能够向外部观众演示一个端到端的关系问答场景并展示关系路径。此外，创建/配置知识库时，管理员能在 30 秒内理解 GraphRAG 开关及场景提示的含义。

## Assumptions

- 当前 query 日志中至少有 15% 的问题属于跨实体关系型问题（需在 Phase 1 验证）。
- 用户能够根据场景提示判断知识库是否适合启用 GraphRAG；对于不适合的场景，用户会选择保持关闭。
- DASHSCOPE_API_KEY 或等效 LLM 调用凭证在 PoC 阶段持续可用，用于 LLM 抽取。

## Open Questions

- GraphRAG 场景提示文案是否需要通过可用性测试或 A/B 测试验证？
- 用户开启 GraphRAG 时，是否需要二次确认其可能带来的构建耗时与成本？
- 是否需要在用户选择开启后，根据内容自动检测并提示"当前知识库看起来不太适合 GraphRAG"？

## Resolved Decisions

- 实体/关系 schema 由系统基于 chunks 采样自动生成并推荐，管理员可在后台一键确认或微调。
- Phase 2 启用 shadow mode：生成阶段同时调用 GraphRAG 但不影响最终答案，仅记录与向量 RAG 的差异用于评估。
