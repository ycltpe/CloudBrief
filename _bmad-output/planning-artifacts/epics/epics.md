---
stepsCompleted:
  - step-01-validate-prerequisites
  - step-02-design-epics
  - step-03-create-stories
inputDocuments:
  - _bmad-output/planning-artifacts/prds/prd-knowledgeAgents-2026-07-01/prd.md
  - _bmad-output/planning-artifacts/architecture/architecture-knowledgeAgents-2026-07-02/ARCHITECTURE-SPINE.md
  - _bmad-output/planning-artifacts/architecture/architecture-knowledgeAgents-2026-07-02/ARCHITECTURE-DISCUSSION.md
---

# CloudBrief 支持副驾 - Epic Breakdown

## Overview

This document provides the complete epic and story breakdown for CloudBrief 支持副驾, decomposing the requirements from the PRD, Architecture spine, and Architecture discussion into implementable stories.

## Requirements Inventory

### Functional Requirements

FR-1: 支持四种知识源格式导入（帮助文档、更新日志、历史工单、内部 FAQ），MVP 通过离线文件/脚本导入，保留来源元信息，导入幂等。

FR-2: 文本切分与片段生成，按语义段落/工单记录/问答对切分，保留来源元信息，切分策略可配置。

FR-3: 建立向量索引与关键词索引（异步任务），通过 API 触发 Celery 任务，返回 task_id 可轮询，原子切换索引。

FR-4: 双路检索召回，向量语义检索 + 关键词检索（BM25），两路结果都包含片段内容与元信息。

FR-5: 融合排序，使用 RRF（k=60）融合向量与关键词检索结果，默认 Top 50，同文档片段去重/降权。

FR-6: Reranker 重排精筛，使用 qwen3-rerank 对查询-片段对打分，输出 Top-N 证据，低分片段过滤。

FR-7: 基于证据生成带引用的答案，LLM 基于 Top-N 片段生成答案，论断级引用标注，引用格式一致。

FR-8: 诚实拒答，证据不足时返回固定话术拒答，不进入 LLM 生成分支，返回诊断信息。

FR-9: 答案时效提示，引用片段更新时间超过阈值时给出"来源可能过期"提示，阈值可配置（默认 90 天）。

FR-10: 会话上下文管理，创建/继续会话，保存历史消息，限制最大长度，持久化到 MySQL。

FR-11: 查询改写，多轮场景下把依赖前文的追问改写成自包含检索查询。

FR-12: 构建评测集，至少 20–30 条问题，覆盖可回答/不可回答/拒答/时效场景，JSON/YAML 维护。

FR-13: 自动评测脚本，一键运行，输出检索命中率、引用准确率、拒答正确率、时效提示正确率及 P50/P90/P95 延迟。

FR-14: 端到端延迟指标，评测集 P90 响应时间 ≤ 30 秒（本地演示环境）。

FR-15: 聊天主界面，使用 @llamaindex/ui 组件实现消息列表、输入框、loading 状态。

FR-16: 引用展示，答案中 [^n] 标记可点击，展开片段原文摘要与元信息。

FR-17: 多轮追问交互，前端自动维护 conversation_id，连续提问。

FR-18: 拒答与时效提示展示，按样式展示拒答文案和时效提醒。

FR-19: 重建索引触发入口，前端按钮调用异步索引重建 API，轮询任务状态。

FR-20: 用户注册与登录，返回 JWT，支持登出与当前用户信息查询。

FR-21: Dashboard 系统概览，展示用户、会话、索引、评测等关键指标。

FR-22: 用户管理（列表、新增、删除），仅 admin 可操作。

FR-23: 系统设置，持久化到数据库并在运行期覆盖 .env 默认值。

FR-24: 聊天助手入口，在管理后台内复用现有 Chat 组件。

FR-25: 知识库目录管理，新建/删除空目录。

FR-26: 知识库文件管理，上传/删除文件，触发整合重建索引。

FR-27: RAGAS 评测审计，列表/详情/人工反馈/导出。

### NonFunctional Requirements

NFR-1: 常见问答端到端延迟 ≤ 30 秒（本地演示环境）。

NFR-2: 可回答问题答案带可点击出处覆盖率 ≥ 90%。

NFR-3: 检索命中率（正确答案出现在 Top-5 证据中）≥ 80%。

NFR-4: 引用准确率（引用与论断一致）≥ 85%。

NFR-5: 拒答正确率（不可回答问题正确拒答且可回答问题未误拒答）≥ 80%。

NFR-6: 时效提示正确率（旧来源问题正确触发提示）≥ 80%。

NFR-7: 答案应简洁，不为了"看起来丰富"而冗长。

NFR-8: 检索召回数量不无限扩大，验证"在有限证据内做对"。

NFR-9: 使用 RAGAS 框架进行自动化 RAG 评估，覆盖上下文相关性（Context Relevance）、上下文精度（Context Precision）、上下文召回率（Context Recall）、忠实度（Faithfulness）、答案相关性（Answer Relevance）。

NFR-10: 支持人工评估流程，允许人工对自动评估结果进行复核与标注。

### Additional Requirements

- 采用"显式阶段管道（Pipes-and-Filters）+ 可插拔 Stage 适配器"范式。
- 每个 Stage 必须实现 `AbstractStage.execute(input: TypedInput) -> TypedOutput`，输入输出为 pydantic.BaseModel。
- LLM 只能接收检索到的 Top-N 片段作为外部知识，不得直接接触 Milvus/BM25/原始文件。
- 拒答必须在进入 LLM 前做硬分支，拒答阈值在 config.py 中可配置。
- 每个非拒答答案必须携带 citations: List[Citation]，包含片段 ID、来源标题、更新时间、原文摘要。
- 索引构建只在 Celery Worker 执行，查询服务只读；新索引构建完成后原子切换 active index 元数据。
- 只有 ConversationStore 允许直接访问 conversations/messages 表。
- 所有外部模型调用通过统一 ModelClient 抽象（OpenAI-compatible HTTP + 重试/超时）。
- 技术栈：Python 3.11+, FastAPI ^0.111+, Celery ^5.3+, Redis 7.x, MySQL 8.x, Milvus 2.3.x, rank-bm25, text-embedding-v3, qwen3-rerank, qwen3.7-plus, Next.js 14 + @llamaindex/ui, Docker Compose。
- 项目目录结构按 backend/ + frontend/ 分离，backend 内分 app/, eval/, data/。
- 本地开发环境通过 docker-compose.yml 一键拉起 Milvus + Redis + MySQL。
- 配置通过 Pydantic Settings 从 .env 加载，禁止硬编码密钥/URL/模型名。
- 结构化 JSON 日志输出到 stdout，每个请求携带 request_id，模型调用记录 latency 和 token 用量。
- API 统一错误返回格式 `{ "error": { "code": ..., "message": ..., "detail": {} } }`。
- 认证采用本地账号 + JWT，密码使用 bcrypt 哈希存储。
- 角色分为 admin / qa / user，接口权限通过 FastAPI Depends 统一校验。
- 系统设置按"数据库 > .env > 代码默认值"优先级加载。
- 知识库目录/文件元数据与物理文件保持一致，删除目录前校验为空。
- LangChain/LlamaIndex 适配器需完整实现，位于 stages/adapters/，与 Native Stage 同接口。
- 评估指标包括上下文相关性（Context Relevance）、上下文精度（Context Precision）、上下文召回率（Context Recall）、忠实度（Faithfulness）、答案相关性（Answer Relevance）。
- 使用 RAGAS 框架实现自动化 RAG 评估。
- 支持人工评估入口，允许人工标注并对比自动评估结果。
- 本地开源 LLM fallback 通过 ModelClient 抽象支持 vLLM / Ollama + Qwen3 开源版。

### UX Design Requirements

UX-DR1: 异步索引重建可视化：在 Web 界面展示重建索引的完整步骤状态（如"读取知识源"→"切分片段"→"生成 Embedding"→"写入 Milvus"→"重建 BM25"→"切换索引"），每步显示 pending / running / completed / failed 状态。

UX-DR2: 使用 `@llamaindex/ui` 的 Workflows 模块（`useWorkflow`、`WorkflowTrigger` 等）实现索引重建的工作流编排与状态展示，保持与聊天界面一致的视觉风格。

UX-DR3: Web 界面需求来自 PRD FR-15 至 FR-19，由 @llamaindex/ui 组件驱动。

### FR Coverage Map

| FR | 所属 Epic | 说明 |
|----|----------|------|
| FR-1 | Epic 2 | 知识源导入 |
| FR-2 | Epic 2 | 文本切分 |
| FR-3 | Epic 2 | 异步索引构建 |
| FR-4 | Epic 3 | 双路检索召回 |
| FR-5 | Epic 3 | RRF 融合 |
| FR-6 | Epic 3 | Reranker 重排 |
| FR-7 | Epic 4 | 带引用生成 |
| FR-8 | Epic 4 | 诚实拒答 |
| FR-9 | Epic 4 | 时效提示 |
| FR-10 | Epic 5 | 会话上下文 |
| FR-11 | Epic 5 | 查询改写 |
| FR-12 | Epic 7 | 评测集构建 |
| FR-13 | Epic 7 | 自动评测脚本 |
| FR-14 | Epic 7 | 延迟指标 |
| FR-15 | Epic 6 | 聊天主界面 |
| FR-16 | Epic 6 | 引用展示 |
| FR-17 | Epic 6 | 多轮追问交互 |
| FR-18 | Epic 6 | 拒答/时效展示 |
| FR-19 | Epic 6 | 重建索引入口 |
| FR-20 | Epic 9 | 注册/登录/登出 |
| FR-21 | Epic 9 | Dashboard |
| FR-22 | Epic 9 | 用户管理 |
| FR-23 | Epic 9 | 系统设置 |
| FR-24 | Epic 9 | 聊天助手入口 |
| FR-25 | Epic 9 | 知识库目录管理 |
| FR-26 | Epic 9 | 知识库文件管理 |
| FR-27 | Epic 9 | RAGAS 评测审计 |
| UX-DR1 | Epic 2 | 索引步骤可视化 |
| UX-DR2 | Epic 2 | Workflows 模块编排 |
| UX-DR3 | Epic 6 | @llamaindex/ui 基础界面 |

## Epic List

### Epic 1: 本地开发环境与系统骨架
开发者/面试官能一键启动完整本地环境，所有服务可运行。
**FRs covered:** 无直接 FR，为所有 Epic 提供基础。

### Epic 2: 知识库导入与索引构建
用户/开发者可以导入四类知识源，系统异步构建可检索索引，并在界面上看到重建进度。
**FRs covered:** FR-1, FR-2, FR-3，UX-DR1, UX-DR2。

### Epic 3: 混合检索与证据精排
用户提问后，系统能从海量知识中召回并精排最相关证据。
**FRs covered:** FR-4, FR-5, FR-6。

### Epic 4: 可信答案生成
用户获得可信、带引用、证据不足时诚实拒答、来源过期时给出提示的答案。
**FRs covered:** FR-7, FR-8, FR-9。

### Epic 5: 多轮会话管理
用户可以像聊天一样连续追问，系统记得上下文并据此改写查询。
**FRs covered:** FR-10, FR-11。

### Epic 6: Web 聊天界面与索引重建可视化
用户通过优美 Web 界面提问、查看引用、触发并观察索引重建。
**FRs covered:** FR-15, FR-16, FR-17, FR-18, FR-19，UX-DR3。

### Epic 7: 效果评测与 RAGAS 评估审计
能量化证明副驾效果，使用 RAGAS 从上下文相关性、精度、召回率、忠实度、答案相关性五个维度自动评估，并在管理后台展示详细评测过程，支持人工复核。
**FRs covered:** FR-12, FR-13, FR-14，NFR-9, NFR-10。

### Epic 8: 框架适配与本地模型 fallback
系统不绑定单一实现，能切换到 LangChain 适配器或本地开源 LLM。
**FRs covered:** 架构 Additional Requirements（LangChain 适配器、本地 LLM fallback）。

### Epic 9: 管理后台
管理员/客服主管通过 /admin 管理用户、配置系统、管理知识库、审计评测；普通支持人员也能在后台内使用聊天助手。
**FRs covered:** FR-20, FR-21, FR-22, FR-23, FR-24, FR-25, FR-26, FR-27。

## Epic 1: 本地开发环境与系统骨架

**Epic Goal:** 开发者/面试官能一键启动完整本地环境，所有服务可运行，后端项目结构清晰，配置、日志、模型调用抽象 ready。

### Story 1.1: 初始化后端项目结构与依赖管理

As a 开发者，
I want 后端项目有清晰的目录结构和依赖配置，
So that 后续功能开发有统一 scaffold。

**Acceptance Criteria:**

**Given** 一个空项目目录
**When** 执行 `mkdir -p backend/app/{api,pipelines,stages/stages/adapters,stores,models,services,tasks,clients} backend/eval backend/data`
**Then** 目录结构符合 ARCHITECTURE-SPINE.md 的 Structural Seed
**And** `backend/pyproject.toml` 声明 Python 3.11+、FastAPI、Celery、Pydantic、SQLAlchemy、PyMySQL、Redis、Milvus Client、rank-bm25、httpx、python-dotenv 等依赖

### Story 1.2: 配置系统与 .env 模板

As a 开发者，
I want 所有环境配置通过 Pydantic Settings 从 .env 加载，
So that 密钥、URL、模型名不会硬编码在代码中。

**Acceptance Criteria:**

**Given** `.env.example` 已提供
**When** 复制为 `.env` 并填写后启动应用
**Then** `backend/app/config.py` 成功加载：DASHSCOPE_API_KEY、MODEL_BASE_URL、EMBEDDING_MODEL、RERANKER_MODEL、LLM_MODEL、MILVUS_URI、REDIS_URL、MYSQL_URL、BM25_INDEX_PATH
**And** 代码中不存在任何硬编码密钥或模型 URL

### Story 1.3: Docker Compose 编排本地依赖

As a 开发者，
I want 一条命令启动 Milvus + Redis + MySQL，
So that 本地演示环境一致且可复现。

**Acceptance Criteria:**

**Given** Docker Desktop 已安装
**When** 执行 `docker-compose up -d`
**Then** Milvus Standalone、Redis、MySQL 容器正常启动
**And** FastAPI 应用能通过配置连接到这三个服务
**And** `docker-compose.yml` 位于项目根目录，包含健康检查

### Story 1.4: 统一 ModelClient 抽象

As a 开发者，
I want 所有外部模型调用走同一个客户端，
So that 重试、超时、日志、密钥管理集中统一。

**Acceptance Criteria:**

**Given** 任意需要调用 DashScope 的 Stage
**When** 调用 `ModelClient.chat.completions.create()` 或 `ModelClient.embeddings.create()`
**Then** 请求自动携带 base_url、api_key、model_name
**And** 失败时按指数退避重试 3 次
**And** 每次调用记录 latency 和 token 用量到结构化日志
**And** ModelClient 同时提供同步调用（for Embedding/Rerank 批量）和异步调用（for LLM 流式/长耗时）两种接口
**And** ModelClient 提供统一方法签名：`embed(texts) -> embeddings`、`rerank(query, passages) -> scored_passages`、`chat(messages, stream=False) -> answer_or_stream`

### Story 1.5: 结构化日志与 request_id

As a 开发者，
I want 每次请求都有唯一 request_id 且日志为 JSON 格式，
So that 问题排查和性能分析有迹可循。

**Acceptance Criteria:**

**Given** 任意 API 请求
**When** 请求进入 FastAPI
**Then** 自动生成并传递 request_id 到所有子调用
**And** 日志输出为 JSON，包含 timestamp、level、request_id、message
**And** Celery 任务也有独立的 task_id 用于追踪

### Story 1.6: MySQL Schema 初始化

As a 开发者，
I want 应用在启动时自动初始化所需的 MySQL 表，
So that 各 Epic 的持久化需求有统一入口。

**Acceptance Criteria:**

**Given** MySQL 已启动
**When** 应用启动时执行 schema 初始化
**Then** 创建以下数据表，并在注释中标注各表由哪个 Epic 首次使用：
- `users`（Epic 9 用户认证）: id, username, password_hash, role, created_at, updated_at
- `conversations`（Epic 5 会话管理）: id, created_at, updated_at
- `messages`（Epic 5 会话管理）: id, conversation_id, role, content, citations_json, is_refusal, created_at
- `index_metadata`（Epic 2 索引构建）: id, collection_name, bm25_index_path, is_active, created_at
- `kb_directories`（Epic 9 知识库管理）: id, name, parent_id, path, created_at, updated_at
- `kb_files`（Epic 9 知识库管理）: id, directory_id, filename, source_type, file_path, file_size, updated_at, created_at
- `system_settings`（Epic 9 系统设置）: id, key, value, updated_at
- `eval_results`（Epic 7 评测审计）: id, question, contexts_json, answer, ground_truth, ragas_scores_json, reasoning_json, human_score, human_note, is_adopted, is_modified, created_at, updated_at
**And** 使用 SQLAlchemy ORM 定义，支持 Alembic 风格迁移（MVP 可手动执行 init）
**And** 各 Epic 的首次 Story 在其 AC 中引用本 Story 说明其所需表已 ready

### Story 1.7: API 接口契约文档

As a 开发者，
I want 前后端共享一份明确的 API 契约，
So that 前端不会等后端接口，后端不会漏掉前端需要的接口。

**Acceptance Criteria：**

**Given** 已完成接口设计
**When** 在 `backend/app/api/` 中实现或在 `docs/api-contract.md` 中记录
**Then** 定义以下接口的请求/响应/错误 schema：
  - `POST /chat`：请求 `{conversation_id?, question: str}`，响应 `{conversation_id, answer, citations[], is_refusal, is_stale, thinking?}` 或 SSE 流
  - `GET /chat/{conversation_id}`：响应 `{messages: [{role, content, citations[], is_refusal, created_at}]}`
  - `POST /index/rebuild`：响应 `{task_id}`
  - `GET /index/tasks/{task_id}`：响应 `{status, steps: [{name, status, error?}], created_at, updated_at}`
  - `POST /auth/register`：请求 `{username, password, role?}`，响应 `{id, username, role}`
  - `POST /auth/login`：请求 `{username, password}`，响应 `{access_token, token_type}`
  - `GET /auth/me`：响应 `{id, username, role}`
  - `GET /admin/dashboard`：响应 `{user_count, conversation_count_today, index_status, latest_eval_scores, recent_tasks}`
  - `GET/POST/DELETE /admin/users` 及 `/admin/users/{id}`
  - `GET/PUT /admin/settings`
  - `GET/POST/DELETE /admin/kb/directories` 及 `/admin/kb/directories/{id}/files`
  - `POST/DELETE /admin/kb/files`
  - `GET /admin/eval/results` 及 `/admin/eval/results/{id}`，`POST /admin/eval/results/{id}/feedback`
**And** 错误统一返回 `{error: {code, message, detail}}`，HTTP 状态码 4xx/5xx 明确
**And** 前端 Story 在 AC 中引用本契约

---

## Epic 2: 知识库导入与索引构建

**Epic Goal:** 用户/开发者可以导入四类知识源，系统异步构建可检索索引，并在界面上看到重建进度。

### Story 2.1: 四种知识源文件解析器（Native + LlamaIndex 双路径）

As a 开发者，
I want 系统既能用轻量自研解析器、也能用 LlamaIndex 的解析能力处理四种知识源文件，
So that 我能展示对文档解析框架的使用，同时理解不依赖框架时的实现。

**Acceptance Criteria：**

**Given** `data/` 目录下有 help.md、changelog.json、 tickets.csv、faq.json 文件
**When** 调用知识源解析器
**Then** Native 解析器用标准库/轻量库（`markdown`/`python-frontmatter`/`json`/`csv`）正确解析为 `List[Document]`
**And** 同时提供 LlamaIndex 解析适配器（如 `SimpleDirectoryReader`、`MarkdownReader`、`JSONReader`），输出同样的 `List[Document]`
**And** 每个 Document 包含 content、source_type、title、updated_at、source_id
**And** 可通过配置切换使用 Native 或 LlamaIndex 解析器
**And** 重复导入同一批文件不会导致片段重复
**And** `data/` 目录作为项目仓库的一部分提交，包含足够支撑演示和评测的合成知识库样例
**And** 解析器返回统一 `Document` DTO，不泄露底层框架类型

### Story 2.2: 文本切分 Stage

As a 开发者，
I want 系统把知识源切分为适合检索的片段，
So that 检索单元既语义完整又不会太大。

**Acceptance Criteria:**

**Given** 一个 Document 对象
**When** 调用 `ChunkingStage.execute()`
**Then** 帮助文档按语义段落切分，工单按记录切分，FAQ 按问答对切分
**And** 每个 Chunk 保留 source_type、title、updated_at、source_id、chunk_index
**And** 切分策略（max_tokens、overlap）可在 config 中配置

### Story 2.3: Native Embedding Stage

As a 开发者，
I want 系统调用 text-embedding-v3 为片段生成向量，
So that 语义检索可用。

**Acceptance Criteria:**

**Given** 一个 Chunk 列表
**When** 调用 `EmbeddingStage.execute()`
**Then** 返回每个 Chunk 的 1024 维向量
**And** 使用 ModelClient 调用 DashScope embedding API
**And** 支持批量调用以提升效率

### Story 2.4: BM25 索引构建

As a 开发者，
I want 系统为片段建立 BM25 倒排索引，
So that 关键词检索可用。

**Acceptance Criteria:**

**Given** 一个 Chunk 列表
**When** 调用 BM25 索引构建逻辑
**Then** 生成可持久化的 BM25 索引文件
**And** 支持从文件加载索引进行查询
**And** 索引文件路径由 config 中的 BM25_INDEX_PATH 指定

### Story 2.5: Milvus Collection 设计与写入

As a 开发者，
I want 系统把片段向量写入 Milvus，
So that 向量检索可用。

**Acceptance Criteria:**

**Given** 已生成 Embedding 的 Chunk 列表
**When** 调用 MilvusStore.write_chunks()
**Then** 在 Milvus 中创建/使用指定 collection，写入向量 + 元信息
**And** collection schema 包含：chunk_id, source_type, title, updated_at, source_id, chunk_index, content
**And** 写入支持批量

### Story 2.6: Celery 异步索引重建任务

As a 用户，
I want 点击重建索引后任务在后台异步执行，
So that 前端不用等待，系统也能处理大量数据。

**Acceptance Criteria:**

**Given** 前端调用 POST /index/rebuild
**When** 后端发布 Celery 任务
**Then** 立即返回 task_id
**And** Celery Worker 按"解析 → 切分 → Embedding → 写 Milvus → 重建 BM25 → 切换索引"顺序执行
**And** 每个步骤记录 `started_at`、`completed_at`、`duration_ms`
**And** 每个步骤生成结构化日志（步骤开始/完成/失败及关键摘要）
**And** Celery Worker 在每个索引步骤完成后通过 **SSE** 向前端推送 step 状态事件，事件包含 `{step_name, status, duration_ms, log_summary, error?}`
**And** 同时保留 `GET /index/tasks/{task_id}` 作为初始状态/重连查询接口，包含每个步骤的 pending/running/completed/failed 状态、耗时和日志摘要

### Story 2.7: 原子切换 Active Index 元数据

As a 系统，
I want 索引重建完成后自动原子切换 active index 指针，
So that 查询服务在重建期间不中断，重建完成后立即使用新索引。

**Acceptance Criteria：**

**Given** 一次索引重建任务正在进行
**When** 新索引构建完成且所有校验通过
**Then** Celery Worker 自动通过 MySQL `index_metadata` 表原子切换 active collection/index 指针
**And** `index_metadata` 表字段为：id, collection_name, bm25_index_path, is_active, created_at
**And** 切换逻辑使用事务：插入新的 is_active=true 记录，同时将旧记录置为 is_active=false
**And** 切换期间查询服务继续使用旧索引
**And** 切换完成后新查询使用新索引
**And** Epic 1 的 MySQL schema 初始化包含 `index_metadata` 表

### Story 2.8: 前端 Workflows 可视化索引进度

As a 用户，
I want 在 Web 界面上看到索引重建的每一步状态，
So that 我知道重建进展和是否出错。

**Acceptance Criteria:**

**Given** 用户点击"重建索引"
**When** 后端返回 task_id 并不断更新步骤状态
**Then** 前端使用 `@llamaindex/ui` 的 Workflows 模块（`useWorkflow`、`WorkflowTrigger`）展示各步骤：读取知识源 / 切分 / Embedding / 写 Milvus / 重建 BM25 / 切换索引
**And** 每步显示 pending / running / completed / failed 状态
**And** 每步显示耗时（duration_ms 格式化）
**And** 每步显示最近 1–3 条日志摘要
**And** 失败时展示错误原因和完整错误日志
**And** 若 Workflows 组件渲染失败，降级为普通步骤列表展示

---

## Epic 3: 混合检索与证据精排

**Epic Goal:** 用户提问后，系统能从海量知识中召回并精排最相关证据。

### Story 3.1: 向量检索 Stage（Milvus）

As a 系统，
I want 根据查询向量从 Milvus 召回语义相近的片段，
So that 找到"换句话说"也能匹配的证据。

**Acceptance Criteria:**

**Given** 一个查询文本
**When** 调用 `VectorRetrievalStage.execute()`
**Then** 先用 Embedding 模型生成查询向量
**And** 从 Milvus 召回 top-k 候选片段（含 content 和元信息）
**And** top-k 可在 config 中配置

### Story 3.2: 关键词检索 Stage（BM25）

As a 系统，
I want 根据查询文本从 BM25 索引召回关键词匹配的片段，
So that 精确术语、错误码、产品名不会漏掉。

**Acceptance Criteria:**

**Given** 一个查询文本
**When** 调用 `BM25RetrievalStage.execute()`
**Then** 从 BM25 索引召回 top-k 候选片段
**And** 结果包含 content 和元信息
**And** top-k 可在 config 中配置

### Story 3.3: RRF 融合 Stage

As a 系统，
I want 把向量检索和关键词检索的结果融合成一个统一列表，
So that 兼顾语义和字面匹配。

**Acceptance Criteria:**

**Given** 两路检索的 top-k 结果
**When** 调用 `HybridFusionStage.execute()`
**Then** 使用 RRF 公式融合，参数 k=60
**And** 输出统一排序后的候选列表（默认 Top 50）
**And** 同一文档的多个片段适当去重或降权

### Story 3.4: Reranker 重排 Stage

As a 系统，
I want 用 qwen3-rerank 对候选片段二次精排，
So that 最相关的证据排到最前。

**Acceptance Criteria:**

**Given** RRF 融合后的候选片段列表
**When** 调用 `RerankingStage.execute()`
**Then** 调用 qwen3-rerank 对每对（查询，片段）打分
**And** 返回 Top-N 片段（默认 N=5，可配置）
**And** 低于阈值的片段被过滤，不进入生成阶段

---

## Epic 4: 可信答案生成

**Epic Goal:** 用户获得可信、带引用、证据不足时诚实拒答、来源过期时给出提示的答案。

### Story 4.1: GenerationPipeline 与 Prompt 模板

As a 系统，
I want 把问题、证据、历史上下文组织成 LLM prompt，
So that LLM 能基于证据生成结构化答案。

**Acceptance Criteria:**

**Given** 用户问题、Top-N 证据、会话历史
**When** 调用 `GenerationPipeline.generate()`
**Then** 组装 prompt，要求 LLM：基于证据回答、每个论断后标注引用 [^id]、不编造无证据的内容
**And** prompt 模板可在配置中替换

### Story 4.2: 引用解析与 Citation DTO

As a 系统，
I want 从 LLM 输出中解析出引用标记，
So that 答案和引用能一起返回给前端。

**Acceptance Criteria:**

**Given** LLM 返回的带 [^1]、[^2] 标注的文本
**When** 调用引用解析逻辑
**Then** 返回 `{answer: str, citations: List[Citation]}`
**And** 每个 Citation 包含 chunk_id、source_title、updated_at、content_summary
**And** 引用编号与 RetrievalResult 中的片段 ID 一致

### Story 4.3: 硬分支拒答逻辑

As a 系统，
I want 证据不足时直接拒答而不调用 LLM，
So that 避免幻觉。

**Acceptance Criteria:**

**Given** Reranker 返回的最高分数低于阈值，或 Top-N 为空
**When** 调用 `GenerationPipeline.generate()`
**Then** 返回 `RefusalResponse`，文案为"根据当前知识库，我找不到足够信息回答这个问题。"
**And** 返回诊断信息：召回片段数、最高 reranker 分数
**And** 不调用 LLM

### Story 4.4: 答案时效提示

As a 系统，
I want 当答案依据来源较旧时给出提示，
So that 用户知道需要复核。

**Acceptance Criteria:**

**Given** 答案引用了更新时间早于阈值（默认 90 天）的片段
**When** 组装最终响应
**Then** 在答案末尾或对应引用旁附加"来源较旧"提示
**And** 阈值在 config 中可配置
**And** 提示不影响答案主体

---

## Epic 5: 多轮会话管理

**Epic Goal:** 用户可以像聊天一样连续追问，系统记得上下文并据此改写查询。

### Story 5.1: ConversationStore CRUD

As a 系统，
I want 在 MySQL 中创建、读取、追加会话消息，
So that 多轮对话有持久化上下文。

**Acceptance Criteria:**

**Given** 一个 conversation_id
**When** 调用 `ConversationStore.get_messages()`
**Then** 返回该会话的历史消息列表
**And** 调用 `ConversationStore.append_message()` 可追加用户/副驾消息
**And** 消息包含 role、content、citations_json、is_refusal、created_at

### Story 5.2: ChatService 会话编排

As a 用户，
I want 发一个问题就能继续之前的对话，
So that 不用重复背景。

**Acceptance Criteria:**

**Given** 一个已存在的 conversation_id
**When** 调用 `ChatService.ask(question, conversation_id)`
**Then** 读取历史消息
**And** 走 RetrievalPipeline + GenerationPipeline
**And** 把用户问题和副驾答案追加到会话
**And** 返回 ChatResponse
**And** 后端暴露 `GET /chat/{conversation_id}`，返回该会话的全部历史消息（含 citations、is_refusal、created_at）

### Story 5.3: 查询改写 Stage

As a 系统，
I want 把依赖上下文的追问改写成自包含查询，
So that 检索链路能理解。

**Acceptance Criteria:**

**Given** 用户追问"那 Excel 格式呢？"和最近两轮历史
**When** 调用 `QueryRewriteStage.execute()`
**Then** 输出"报表导出为 Excel 格式无法打开怎么办？"
**And** 改写后的查询只用于检索，不改变用户看到的原始问题
**And** 策略可配置：简单拼接或 LLM-based 改写

---

## Epic 6: Web 聊天界面与索引重建可视化

**Epic Goal:** 用户通过优美 Web 界面提问、查看引用、触发并观察索引重建。

### Story 6.1: Next.js 项目初始化与 @llamaindex/ui 集成

As a 开发者，
I want 前端项目能使用 @llamaindex/ui 组件，
So that 聊天界面专业且一致。

**Acceptance Criteria:**

**Given** 空 `frontend/` 目录
**When** 初始化 Next.js 14 项目并安装 `@llamaindex/ui`
**Then** 能成功渲染 `@llamaindex/ui` 的 Chat 组件
**And** 配置好 API base URL（从 .env 读取）

### Story 6.2: 聊天主界面

As a 支持人员，
I want 在网页上输入问题并看到回答，
So that 我能使用副驾。

**Acceptance Criteria:**

**Given** 用户打开首页
**When** 输入问题并发送
**Then** 显示 loading 状态
**And** 后端返回后展示副驾答案
**And** 消息列表区分用户和副驾
**And** 当后端返回 4xx/5xx 错误时，显示友好错误提示（如"服务繁忙，请稍后重试"），不展示空白答案

### Story 6.3: 引用展示组件

As a 支持人员，
I want 点击答案里的引用标记就能看到原文，
So that 我能复核答案依据。

**Acceptance Criteria:**

**Given** 答案中包含 [^1]、[^2] 标记
**When** 用户点击引用标记
**Then** 弹出/展开片段原文摘要
**And** 显示来源标题、更新时间、来源类型

### Story 6.4: 多轮追问交互

As a 支持人员，
I want 在同一聊天窗口连续提问，
So that 我能顺着追问。

**Acceptance Criteria:**

**Given** 用户已发送过问题
**When** 在同一页面继续输入新问题
**Then** 前端自动携带同一个 conversation_id
**And** 后端根据会话历史做查询改写

### Story 6.5: 拒答与时效提示样式

As a 支持人员，
I want 清楚看到"找不到答案"和"来源较旧"的提示，
So that 我不会误信。

**Acceptance Criteria:**

**Given** 后端返回拒答
**When** 前端渲染时
**Then** 显示固定拒答文案，不展示引用
**And** 给定后端返回答案+时效提示
**Then** 以黄色警告条或引用旁图标展示"来源较旧"提示

### Story 6.6: 重建索引入口与任务状态 SSE

As a 支持人员/开发者，
I want 在界面上触发索引重建并通过 SSE 实时看到进度，
So that 我能更新知识库。

**Acceptance Criteria：**

**Given** 用户在管理面板或工具栏点击"重建索引"
**When** 前端调用 POST /index/rebuild
**Then** 拿到 task_id 并建立 SSE 连接到 `/index/tasks/{task_id}/events`
**And** 实时接收每个索引步骤的状态更新、耗时和日志摘要
**And** 使用 @llamaindex/ui Workflows 展示各步骤状态、耗时和日志摘要
**And** SSE 断开时可通过 GET /index/tasks/{task_id} 重连获取当前状态、历史步骤耗时和日志
**And** 完成后提示用户并展示总耗时

---

## Epic 7: 效果评测

**Epic Goal:** 能量化证明副驾效果（命中率、引用准确率、拒答正确率、延迟），定位失败 case。

### Story 7.1: 合成评测集构建

As a 开发者，
I want 构造覆盖四类知识源和多种场景的评测问题，
So that 能量化系统效果。

**Acceptance Criteria:**

**Given** 已准备的合成知识库
**When** 编写 eval/eval_set.json
**Then** 至少包含 20–30 条问题
**And** 覆盖：可回答、不可回答（应拒答）、旧来源（应时效提示）
**And** 每条问题标注期望答案要点、期望引用 chunk_id、是否应拒答、是否涉及时效

### Story 7.2: 自动评测脚本与指标计算

As a 开发者，
I want 一键运行评测并看到指标报告，
So that 我能定位失败 case。

**Acceptance Criteria:**

**Given** 已构建的评测集
**When** 运行 `python -m eval.run_eval`
**Then** 对每条问题调用 ChatService，获取 answer 和 retrieval contexts
**And** 输出 JSON/CSV 报告，包含：
  - 检索命中率（正确答案在 Top-k 证据中）
  - 引用准确率（引用与论断一致）
  - 拒答正确率（不可回答正确拒答、可回答未误拒）
  - 时效提示正确率
**And** 同时调用 RAGAS 计算 context_precision、context_recall、faithfulness、answer_relevancy
**And** 报告包含每个问题的详细结果，便于定位失败 case

### Story 7.3: 延迟指标记录

As a 开发者，
I want 评测同时记录端到端延迟，
So that 我能验证 30 秒目标。

**Acceptance Criteria:**

**Given** 运行评测脚本
**When** 每个问题被调用
**Then** 记录从请求到完整响应的耗时
**And** 最终报告输出 P50 / P90 / P95 延迟
**And** 常见问题的 P90 延迟 ≤ 30 秒（本地演示环境）

### Story 7.4: 集成 RAGAS 自动化评估并存储过程数据

As a 开发者，
I want 用 RAGAS 自动计算 RAG 专用指标并把详细过程存入数据库，
So that 我能从检索和生成两个维度量化系统质量，并在管理后台查看过程。

**Acceptance Criteria：**

**Given** 评测集包含 question、contexts、answer、ground_truth
**When** 运行 RAGAS 评估
**Then** 计算并输出以下指标：
  - context_relevance（上下文相关性）
  - context_precision（上下文精度）
  - context_recall（上下文召回率）
  - faithfulness（忠实度）
  - answer_relevance（答案相关性）
**And** 把每个评测样本的详细数据写入 `eval_results` 表：
  - question, contexts_json, answer, ground_truth
  - ragas_scores_json：各指标分数
  - reasoning_json：RAGAS 中间判断（如哪些 context 被判定为 relevant，若可用）
**And** 指标结果同时输出 JSON/CSV 报告
**And** 允许配置 judge LLM（默认复用系统配置的 LLM）

### Story 7.5: 评测结果基础接口（数据消费）

As a 开发者，
I want 把 RAGAS 评测产生的结果通过基础 REST 接口暴露出来，
So that 管理后台（Epic 9）或其他消费者可以读取评测数据。

**Acceptance Criteria：**

**Given** `eval_results` 表已有数据
**When** 调用 `GET /eval/results`
**Then** 返回评测记录列表，包含：id, question, answer, ground_truth, ragas_scores_json, human_score, is_adopted, is_modified, created_at
**And** 支持 limit/offset 分页

**Given** 一条存在的评测记录
**When** 调用 `GET /eval/results/{id}`
**Then** 返回该记录完整字段：question, contexts_json, answer, ground_truth, ragas_scores_json, reasoning_json, human_score, human_note, is_adopted, is_modified

**And** 管理后台的评测列表/详情/人工反馈 UI 由 Epic 9 的 Story 9.10-9.11 负责实现

---

## Epic 8: 框架适配与本地模型 fallback

**Epic Goal:** 系统不绑定单一实现，能切换到 LangChain 适配器或本地开源 LLM。

### Story 8.1: LangChain 检索适配器

As a 开发者，
I want 用 LangChain 实现同样的检索 Stage 接口，
So that 能对比自研与框架方案。

**Acceptance Criteria:**

**Given** 已实现 Native 检索 Stage
**When** 实现 `stages/adapters/lc_retrieval.py`
**Then** 它实现 `AbstractStage.execute()` 接口
**And** 内部使用 LangChain 的 Retriever / Document 抽象
**And** 输出与 Native Stage 同结构的 RetrievalResult
**And** 可通过配置切换使用 LangChain 适配器

### Story 8.2: LangChain 生成适配器

As a 开发者，
I want 用 LangChain 实现同样的生成 Stage 接口，
So that 生成链路也能对比。

**Acceptance Criteria:**

**Given** 已实现 Native 生成 Stage
**When** 实现 `stages/adapters/lc_generation.py`
**Then** 它实现 `AbstractStage.execute()` 接口
**And** 内部使用 LangChain 的 LLMChain / LCEL
**And** 返回与 Native Stage 同结构的 GenerationResult（含 citations）
**And** 可通过配置切换使用 LangChain 适配器

### Story 8.3: 本地开源 LLM fallback

As a 开发者，
I want 在 qwen3.7-plus 不可用时切换到本地开源 LLM，
So that 系统不依赖单一云供应商。

**Acceptance Criteria:**

**Given** 配置中 LLM_PROVIDER=local
**When** 调用 ModelClient
**Then** 请求被路由到本地 vLLM 或 Ollama 服务
**And** 使用 OpenAI-compatible 接口
**And** 本地模型默认使用 Qwen3 开源版（如 qwen3-7b）
**And** 切换后 GenerationPipeline 行为一致

---

## Epic 9: 管理后台

**Epic Goal:** 管理员/客服主管通过 /admin 管理用户、配置系统、管理知识库、审计评测；普通支持人员也能在后台内使用聊天助手。

### Story 9.1: JWT 认证与账号注册

As a 新用户，
I want 通过用户名密码注册并登录系统，
So that 我能使用管理后台和聊天助手。

**Acceptance Criteria:**

**Given** 未认证用户访问注册页
**When** 提交用户名、密码
**Then** 后端校验用户名唯一，密码使用 bcrypt 哈希存储
**And** 新用户默认角色为 `user`
**And** 登录成功后返回 JWT access token
**And** 后端暴露 `POST /auth/register`、`POST /auth/login`、`POST /auth/logout`、`GET /auth/me`
**And** 受保护接口拒绝无 token 或过期 token 的请求

### Story 9.2: 角色权限中间件

As a 系统，
I want 不同角色访问不同接口，
So that admin 专属功能不被普通用户调用。

**Acceptance Criteria:**

**Given** 已实现 JWT 认证
**When** 在路由上应用 `Depends(require_role("admin"))`
**Then** 仅 `admin` 角色可访问用户管理、系统设置、知识库管理接口
**And** `admin` 和 `qa` 均可访问 RAGAS 评测审计接口
**And** `user` 仅可访问聊天助手和 Dashboard 只读数据
**And** 越权访问返回 403，错误码 `FORBIDDEN`

### Story 9.3: Dashboard 聚合接口与页面

As a 管理员，
I want 登录后第一眼看到系统关键指标，
So that 快速了解运行状态。

**Acceptance Criteria:**

**Given** 管理后台已有数据
**When** 打开 `/admin/dashboard`
**Then** 后端 `GET /admin/dashboard` 返回：用户总数、今日会话数、当前索引状态、最近评测平均分、最近重建任务
**And** 前端以卡片/列表形式展示上述指标
**And** 页面加载失败时显示友好错误提示

### Story 9.4: 用户管理（列表/新增/删除）

As a 管理员，
I want 在后台管理用户账号，
So that 控制谁能使用系统。

**Acceptance Criteria:**

**Given** 已登录 admin 用户
**When** 打开"用户管理"页
**Then** 调用 `GET /admin/users` 展示用户列表（ID、用户名、角色、创建时间）
**And** 支持按用户名搜索、按角色筛选、分页
**And** 可新增用户：填写用户名、初始密码、角色，调用 `POST /admin/users`
**And** 可删除用户：二次确认后调用 `DELETE /admin/users/{id}`
**And** 禁止删除最后一个 admin
**And** 非 admin 访问用户管理接口返回 403

### Story 9.5: 系统设置持久化

As a 管理员，
I want 在后台调整系统运行参数，
So that 无需重启即可生效。

**Acceptance Criteria:**

**Given** 已登录 admin 用户
**When** 打开"系统设置"页
**Then** 展示当前设置：拒答阈值、时效阈值天数、最大历史轮数、请求超时
**And** 修改后调用 `PUT /admin/settings` 保存到 `system_settings` 表
**And** 新设置覆盖内存中的配置值，立即对后续请求生效
**And** 仅 admin 可修改设置

### Story 9.6: 知识库目录管理

As a 管理员，
I want 在后台管理知识库目录结构，
So that 知识源文件有序组织。

**Acceptance Criteria:**

**Given** 已登录 admin 用户
**When** 打开"知识库管理"页
**Then** 左侧展示目录树，支持展开/收起
**And** 可新建目录：指定父目录和目录名，后端在 `data/` 下创建物理目录并写入 `kb_directories` 表
**And** 可删除空目录：删除前校验目录下无文件
**And** 后端暴露 `GET /admin/kb/directories`、`POST /admin/kb/directories`、`DELETE /admin/kb/directories/{id}`

### Story 9.7: 知识库文件上传与删除

As a 管理员，
I want 在指定目录上传或删除知识源文件，
So that 知识库内容可维护。

**Acceptance Criteria:**

**Given** 已登录 admin 用户
**When** 在知识库管理页选择目录并上传文件
**Then** 文件保存到 `data/<dir>/` 下对应物理路径
**And** 写入 `kb_files` 表元数据（文件名、目录 ID、来源类型、文件路径、更新时间）
**And** 可删除文件：删除物理文件和元数据记录，二次确认
**And** 支持 Markdown/JSON/CSV 格式
**And** 后端暴露 `GET /admin/kb/directories/{id}/files`、`POST /admin/kb/files`、`DELETE /admin/kb/files/{id}`

### Story 9.8: 知识库整合重建索引

As a 管理员，
I want 上传文件后触发全量索引重建，
So that 新知识源可被检索。

**Acceptance Criteria:**

**Given** 已登录 admin 用户
**When** 点击"整合重建索引"按钮
**Then** 调用现有 `POST /index/rebuild`，基于当前 `data/` 下所有物理文件重建索引
**And** 前端展示 SSE 实时进度或轮询任务状态
**And** 重建完成后提示"索引已更新"
**And** 删除文件/目录后不自动重建，而是提示"索引已过期，请手动重建"

### Story 9.9: 聊天助手后台入口

As a 已登录用户，
I want 在管理后台内直接使用聊天助手，
So that 不用切换页面。

**Acceptance Criteria:**

**Given** 已登录用户
**When** 点击左侧"聊天助手"菜单
**Then** 右侧加载现有 `Chat` 组件
**And** 前端路由为 `/admin/chat`
**And** 请求自动携带 JWT token

### Story 9.10: RAGAS 评测审计列表页

As a 客服主管/管理员，
I want 在后台查看所有评测记录，
So that 定位质量差的 case。

**Acceptance Criteria:**

**Given** `eval_results` 表已有数据
**When** 打开"/admin/eval"
**Then** 展示评测列表：问题、答案类型、RAGAS 各指标分数、人工评分、创建时间
**And** 支持按分数范围、是否有人工评分筛选，支持分页
**And** `admin` 和 `qa` 可访问，`user` 不可访问

### Story 9.11: RAGAS 评测详情与人工复核

As a 客服主管，
I want 查看单次评测的详细过程并给出人工评分，
So that 验证自动评估是否可信。

**Acceptance Criteria:**

**Given** 已登录 admin 或 qa 用户
**When** 点击评测记录"查看详情"
**Then** 展示：Question、Ground Truth、Answer、Retrieved Contexts、RAGAS 指标分数与 reasoning
**And** 提供人工评分区：1–5 分、备注、是否采用、是否修改
**And** 提交后调用 `POST /admin/eval/results/{id}/feedback` 更新 `eval_results` 表
**And** 支持导出人工标注结果（CSV/JSON）

### Story 9.12: 管理后台前端布局与路由

As a 前端开发者，
I want 管理后台有统一的左侧菜单和右侧内容区，
So that 各功能模块有一致的导航体验。

**Acceptance Criteria:**

**Given** 已登录用户
**When** 访问 `/admin/*`
**Then** 渲染统一布局：顶部用户信息/退出、左侧菜单（Dashboard、系统设置、用户管理、聊天助手、知识库管理、RAGAS 评测审计）
**And** 右侧渲染对应功能模块
**And** 未登录用户访问 `/admin/*` 被重定向到 `/admin/login`
**And** 前端使用 Next.js App Router，`/admin/layout.tsx` 提供共享布局
**And** 菜单根据用户角色动态显示（例如 `user` 不显示用户管理）

