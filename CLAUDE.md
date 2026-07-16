# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

CloudBrief 支持副驾 —— 面向企业内部的 Enterprise RAG 知识问答系统，求职作品集案例。采用 FastAPI + Next.js 14 全栈架构，检索链路为混合检索（BM25 + 向量）→ RRF(k=60) → Rerank → 带引用生成，并支持硬分支拒答与时效提示。

## 常用命令

### 依赖启动

项目依赖 Milvus、Redis、MySQL，通过 Docker Compose 一键启动：

```bash
docker compose up -d
```

本地映射端口（避免与已有服务冲突）：
- Milvus: `19531`
- Redis: `6381`
- MySQL: `3307`
- MinIO Console: `9003`

### 后端

后端目录为 `backend/`，使用 `uv` 管理依赖，Python 版本要求 `>=3.11`。

```bash
cd backend
uv venv --python /Users/yechen/.local/bin/python3.11
uv sync
```

启动 API 服务：

```bash
uv run uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload
```

启动 Celery Worker（索引重建、单文件索引、图索引分别路由到 `kb.index.rebuild`、`kb.index.single`、`kb.graph.rebuild` 队列）：

```bash
uv run celery -A app.celery_app worker -Q kb.index.rebuild,kb.index.single,kb.graph.rebuild --loglevel=info
```

运行全部测试：

```bash
uv run pytest
```

运行单个测试文件：

```bash
uv run pytest tests/test_parsing.py
```

代码检查：

```bash
uv run ruff check .
```

RAGAS 评测：

```bash
uv run python -m eval.run_eval
```

### 前端

前端目录为 `frontend/`，使用 Next.js 14 + Tailwind CSS。

```bash
cd frontend
npm install
npm run dev
```

构建：

```bash
npm run build
```

检查：

```bash
npm run lint
```

前端默认运行在 `http://localhost:3000`（被占用时自动使用 3001）。

## 架构总览

### 后端结构

后端按功能分层：

- `app/api/`：FastAPI 路由。`chat.py`、`index.py` 为公开接口；`admin/` 下为 `/admin/*` 管理后台接口（用户、设置、知识库、评测、Dashboard）。
- `app/services/`：业务编排。`ChatService` 负责完整问答流程；`IndexService` 负责触发/查询 Celery 索引任务及 SSE 事件流；`SettingsService` 提供运行期配置读写。
- `app/pipelines/`：检索与生成管线。
  - `RetrievalPipeline`：Native 路径下执行 Vector + BM25 → HybridFusion(RRF) → Rerank；可通过 `retrieval_adapter` 切换为 LangChain 适配器。
  - `GenerationPipeline`：硬分支拒答 → LLM 生成 → 引用解析 → 时效检查。
- `app/stages/`：管线中的可复用阶段，包括解析、切分、Embedding、向量检索、BM25 检索、混合融合、Rerank、生成 LLM、引用解析、查询改写。`adapters/` 下包含 LangChain / LlamaIndex 适配实现。
- `app/clients/model_client.py`：统一封装 Embedding / Rerank / LLM 调用，集中管理 DashScope 密钥、重试、超时与日志。
- `app/stores/`：存储封装。`MilvusStore`、`BM25Store`、`ConversationStore`、`SettingsStore`、`KbStore`、`IndexMetadataStore` 分别对应向量、稀疏索引、会话、配置、知识库文件、索引元数据。
- `app/tasks/indexing.py`：Celery 任务。`rebuild_index_task` 全量重建索引；`index_file_task` 单文件增量索引，采用 copy-on-write 合并现有索引后原子切换。
- `app/models/schemas.py`：Pydantic DTO，所有接口出入参统一在此定义。
- `app/config.py`：统一配置入口，环境变量从项目根目录 `.env` 加载，禁止代码中硬编码密钥/URL/模型名。

### 索引构建流程

1. 解析 `backend/data/`（或知识库上传文件）为 `Document`。支持格式：Markdown / JSON / CSV / TXT / PDF / DOCX / XLSX（`.doc`/`.xls` 老格式不支持）。PDF 无文字层页自动回退 OCR（DashScope qwen-vl-ocr，逐页心跳）；超过 `PDF_BATCH_PAGE_THRESHOLD` 页的 PDF 按 `PDF_PAGE_BATCH_SIZE` 页一批解析并推送进度心跳；单文件解析失败只跳过不中断整批重建，全部失败则中止重建（原索引保持不变）。已知限制：DOCX 仅提取正文段落与表格（页眉/页脚/脚注/文本框不提取）；XLSX 读取公式缓存值，未经 Excel/WPS 保存计算过的公式单元格为空（建议先保存再上传）；单份 PDF 超过 `PDF_MAX_PAGES`（默认 2000）页拒绝解析。
2. `ChunkingStage` 切分为 `Chunk`。
3. `EmbeddingStage` 调用 DashScope text-embedding-v3 生成向量。
4. 新 collection + 新 BM25 文件写入。
5. Redis 分布式锁保护下原子切换活跃索引（`IndexMetadataStore.switch_active`）。
6. 通过 Redis Pub/Sub 发布每阶段事件；`/index/tasks/{id}/events` 以 SSE 推送给前端。

### 检索与生成流程

1. `ChatService` 读取会话历史，调用 `QueryRewriteStage` 改写查询。
2. `RetrievalPipeline.retrieve(query)`：
   - `VectorRetrievalStage`：Milvus 向量召回。
   - `BM25RetrievalStage`：基于 `rank-bm25` + `jieba` 中文分词的稀疏召回。
   - `HybridFusionStage`：RRF(k=60) 融合。
   - `RerankingStage`：根据 `reranker_provider` 选择 DashScope qwen3-rerank 或本地 vLLM/TEI 部署的重排模型（如 `BAAI/bge-reranker-large`），返回 Top-N；不可用时回退到融合分数。
3. `GenerationPipeline`：若 chunk 为空或 `max_score < refusal_threshold`（默认 0.3）则硬分支拒答；否则调用 `GenerationLLMStage` 生成答案。
4. `CitationParserStage` 从生成文本中提取引用标记并映射到检索结果；若任一来源超过 `stale_threshold_days`（默认 90 天）则标记 `is_stale`。
5. 答案与用户消息持久化到 MySQL。

### 认证与权限

- 使用 JWT（HS256），token 同时通过 `Authorization: Bearer` Header、`access_token` Cookie、URL query `token` 读取，兼容 SSE/SSR 场景。
- `get_current_user_optional` 允许匿名访问；`require_role("admin", ...)` 用于管理接口。
- 角色：admin / qa / user。

### 前端结构

- `app/page.tsx`：首页，左侧 `IndexRebuildPanel`，右侧 `Chat`。
- `app/admin/`：管理后台页面（dashboard、settings、kb、eval、users、chat、login、register）。
- `components/`：聊天、索引重建面板、引用展示、主题切换等。
- `hooks/`：`useTaskStream` 轮询 + SSE 监听索引任务；`useIndexRebuild` 封装重建交互。
- `lib/auth.ts`：登录、token 管理、`authFetch`。
- `middleware.ts`：保护 `/admin/*` 路由，未登录重定向到 `/admin/login`。
- 样式：Tailwind CSS + CSS 变量定义语义化颜色；`next-themes` 管理明亮/暗黑模式。新增页面必须同时支持明亮和暗黑模式。

### 运行期配置

所有配置按「数据库覆盖 → `.env` → 代码默认值」三级生效，统一入口是 `SettingsService.get_runtime_value(key)`：

- **数据库覆盖**：管理后台「系统设置」页保存的值存于 MySQL `system_settings` 表，优先级最高。DB 读取带进程级缓存（全量快照 + 60s TTL），保存/恢复默认时自动失效；DB 不可用时负缓存空快照并回退，不阻断业务链路。
- **`.env`**：pydantic `Settings`（`app/config.py`）显式设置的字段，作为中间层。
- **代码默认值**：`config.py` 字段默认值兜底。

注册表约 55 项配置，按 11 个分组展示（业务阈值 / 功能开关 / 适配器 / 大语言模型 / 向量模型 / Reranker 模型 / 文档解析 / GraphRAG 监控 / 存储连接 / 认证与安全 / 系统）。三个模型组各自独立配置 Provider（`dashscope` 云端 / `local` 本地）、云端密钥与端点、本地服务地址，`local` 为权威路径不回退云端；前端按 Provider 值条件渲染云端/本地字段块，每项带三个语义标记：

- `secret`（如 `llm_api_key`、`jwt_secret_key`、`mysql_url`、`neo4j_password`）：API 出参固定脱敏为 `********`；前端提交空值或掩码值视为不修改，防止脱敏值写回覆盖真实密钥。
- `restart_required`（连接串、端口、日志级别等启动期读取项）：DB 覆盖在下次重启后生效。`mysql_url` 为自举读取：`app/stores/db.py` 先用 .env 连接串查出 DB 覆盖值，再以覆盖值创建连接池，失败时回退 .env。
- `requires_reindex`（`embedding_model`、`embedding_dim`、`parser`）：修改后需重建索引才能对存量数据生效，前端保存时会弹确认。

管理接口：`GET/PUT /admin/settings`、`GET /admin/settings/runtime/{key}`、`DELETE /admin/settings/{key}`（删除 DB 覆盖，恢复 .env/默认值）。

**开发约束**：业务代码新增配置读取时，运行期生效的值必须走 `SettingsService.get_runtime_value()`，禁止直接读 `get_settings()` 的业务字段（启动期一次性读取的连接/端口类除外，且必须在注册表标记 `restart_required`）；新增配置项需同时在 `config.py` 声明字段（保证 .env 可表达）并在 `settings_service.py` 注册 `SettingMeta`。

### 关键配置

配置项集中在项目根目录 `.env`（作为三级链中的兜底默认层，均可在管理后台覆盖），从 `.env.example` 复制后填写：

- `LLM_API_KEY` / `EMBEDDING_API_KEY` / `RERANKER_API_KEY` / `OCR_API_KEY`：各模型组的云端调用密钥（冗余设计，各用各的）。
- `LLM_BASE_URL` / `EMBEDDING_BASE_URL` / `RERANK_BASE_URL` / `OCR_BASE_URL`：各组云端端点。
- `LLM_PROVIDER` / `EMBEDDING_PROVIDER` / `RERANKER_PROVIDER`：`dashscope` 或 `local`。`local` 为权威路径、不回退云端；`dashscope` 模式下本地端点作为失败降级。切换 `EMBEDDING_PROVIDER` 后必须重建索引（向量空间与维度随模型变化）。
- `MILVUS_URI`、`REDIS_URL`、`MYSQL_URL`、`BM25_INDEX_PATH`：存储连接（启动期读取，后台覆盖需重启生效）。
- `REFUSAL_THRESHOLD`、`STALE_THRESHOLD_DAYS`、`MAX_HISTORY_ROUNDS`、`REQUEST_TIMEOUT`：业务阈值。
- `PDF_BATCH_PAGE_THRESHOLD`（默认 50）、`PDF_PAGE_BATCH_SIZE`（默认 25）：大 PDF 页级分批解析阈值与批大小。
- `OCR_ENABLED`（默认 true）、`OCR_MODEL`（默认 `qwen-vl-ocr-latest`）、`OCR_TIMEOUT_SECONDS`（默认 120）、`PDF_OCR_DPI`（默认 200）：扫描件 OCR 开关与参数。
- `PDF_MAX_PAGES`（默认 2000）：单份 PDF 页数上限，防止超大文件长时间占满索引 worker。
- `BACKEND_PORT`：FastAPI 端口（默认 8001）。

### 本地 Reranker 部署

如需使用本地重排模型，在 `.env` 中设置 `RERANKER_PROVIDER=local` 并填写 `LOCAL_RERANKER_URL` 与 `LOCAL_RERANKER_MODEL`（默认 `BAAI/bge-reranker-large`）。项目已提供 Docker Compose 服务：

```bash
docker compose --profile reranker up -d
```

该服务默认监听 `127.0.0.1:8000`，模型权重首次启动时自动下载并持久化到 `vllm_model_cache` 卷。管理员也可在「系统设置」页面随时切换 `reranker_provider`，切换后请确保本地服务已启动；若本地服务不可用，`RerankingStage` 会自动回退到 Hybrid Fusion 分数。

## 开发注意事项

- 后端启动前需确保 `.env` 存在且各模型组的 `*_API_KEY` 有效，否则模型调用会失败。
- 首次运行问答前必须先执行一次索引重建（通过前端「重建索引」按钮或调用 `POST /index/rebuild`），否则 `RetrievalPipeline` 会抛出 `No active index found`。
- Celery Worker 必须监听 `kb.index.rebuild` 和 `kb.index.single` 队列，否则索引任务不会被消费。
- 前端新增页面、组件、弹窗等 UI 必须同时支持明亮和暗黑模式：使用 Tailwind 语义化颜色变量（如 `bg-card`、`text-card-foreground`、`dark:*`），并在 `globals.css` 中维护 `:root` 与 `.dark` 两套变量。
- `.env` 与 `.venv`、`.next` 等已加入 `.gitignore`，不要提交。

## context 管理
- context 使用大于 30% 自动压缩