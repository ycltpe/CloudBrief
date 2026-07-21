---
story_id: 1.1
story_key: 1-1-init-backend-project-structure
epic: 1
epic_title: 本地开发环境与系统骨架
status: ready-for-dev
created: 2026-07-17
last_updated: 2026-07-17
---

# Story 1.1: 初始化后端项目结构与依赖管理

## Story Foundation

**As a** 开发者，
**I want** 后端项目有清晰的目录结构和依赖配置，
**So that** 后续功能开发有统一 scaffold。

### 来源
- Epic: `epics.md` Epic 1 — 本地开发环境与系统骨架
- PRD: `_bmad-output/planning-artifacts/prds/prd-knowledgeAgents-2026-07-01/prd.md`
- Architecture Spine: `_bmad-output/planning-artifacts/architecture/architecture-knowledgeAgents-2026-07-02/ARCHITECTURE-SPINE.md`
- Project Context: `_bmad-output/project-context.md`

---

## Acceptance Criteria（来自 Epic）

**Given** 一个空项目目录
**When** 执行 `mkdir -p backend/app/{api,pipelines,stages/stages/adapters,stores,models,services,tasks,clients} backend/eval backend/data`
**Then** 目录结构符合 ARCHITECTURE-SPINE.md 的 Structural Seed
**And** `backend/pyproject.toml` 声明 Python 3.11+、FastAPI、Celery、Pydantic、SQLAlchemy、PyMySQL、Redis、Milvus Client、rank-bm25、httpx、python-dotenv 等依赖

---

## Current State Assessment（关键！项目已存在）

> **注意**：本项目已经历多轮开发，git 历史显示已有 `backend/`、`frontend/`、`docker-compose.yml`、核心 Stage/Store/Service 实现。本 Story 的目标**不是从零创建**，而是：
> 1. 验证现有结构是否符合 Architecture Spine；
> 2. 补齐缺失的目录/文件；
> 3. 确保 `pyproject.toml` 依赖完整、版本正确、与当前代码一致；
> 4. 为后续 Story 提供稳定的 scaffold。

### 已确认存在的内容

- `backend/pyproject.toml` 已声明 Python >=3.11、FastAPI、Celery、Pydantic、SQLAlchemy、PyMySQL、Redis、Milvus、rank-bm25、jieba、httpx、sse-starlette、structlog、ragas、langchain、llama-index、bcrypt、python-jose 等依赖。
- `backend/app/` 下已存在：
  - `api/`（含 `admin/` 子路由）
  - `clients/`
  - `models/`
  - `pipelines/`
  - `services/`
  - `stages/`（含 `adapters/` 子目录）
  - `stores/`
  - `tasks/`
  - `main.py`、`config.py`、`celery_app.py`、`logging_config.py`、`dependencies.py`、`metrics.py`
- `backend/eval/` 与 `backend/data/` 已存在。
- `docker-compose.yml` 已包含 Milvus、Redis、MySQL、Neo4j、本地 reranker 服务。

### 可能存在的 Gap（需开发时逐项核查）

1. **目录命名偏差**：Architecture Spine 中部分目录名与现有代码可能不一致，例如：
   - Spine 写 `stages/bm25.py`，现有代码为 `stages/bm25_retrieval.py` —— 这是合理的演进，但需在 Story 中确认命名一致性。
   - Spine 写 `stores/bm25_store.py`，现有代码为 `stores/bm25_store.py` —— 已一致。
2. **`stages/adapters/` 内容**：需确认 LangChain / LlamaIndex 适配器是否完整实现同接口的 Stage。
3. **`.env.example` 是否存在**：项目根目录需有 `.env.example` 作为配置模板（Story 1.2 负责，但本 Story 需确保 `.env` 读取机制可用）。
4. **`backend/tests/` 目录与 `conftest.py`**：测试基础设施是否已就位。
5. **`pyproject.toml` 的版本与代码实际依赖是否一致**：例如是否已加入 `langgraph`/`langgraph-checkpoint`（Agentic RAG 需要），以及 `neo4j` 是否在 optional-dependencies 的 `graphrag` 组中。

---

## Developer Context

### 本 Story 的边界

- **不实现业务逻辑**：不编写 ChatService、RetrievalPipeline、GenerationPipeline 等具体实现。
- **不修改功能代码**：除非发现结构不一致导致后续 Story 无法基于当前代码继续。
- **重点在于"scaffold 验收"**：把现有项目状态与 Architecture Spine 对齐，输出一份结构核验报告，并补齐缺失项。

### 与后续 Story 的关系

| 后续 Story | 依赖本 Story 提供的什么 |
|---|---|
| 1.2 配置系统与 .env 模板 | 依赖 `backend/app/config.py` 与 `pyproject.toml` 已就位 |
| 1.3 Docker Compose 编排 | 依赖 `docker-compose.yml` 与项目目录结构 |
| 1.4 ModelClient 抽象 | 依赖 `backend/app/clients/` 目录与依赖包（httpx、tenacity） |
| 1.5 结构化日志 | 依赖 `backend/app/logging_config.py` 与 `structlog` |
| 1.6 MySQL Schema | 依赖 `backend/app/stores/db.py` 与 SQLAlchemy/PyMySQL |
| 2.x 知识库索引 | 依赖 `backend/app/stages/`、`backend/app/pipelines/`、`backend/app/tasks/` 目录 |

---

## Architecture Compliance

### 必须遵循的 Architecture Decision Records

- **AD-1 Pipeline 阶段契约**：每个 Stage 必须实现 `AbstractStage.execute(input: TypedInput) -> TypedOutput`，输入输出为 `pydantic.BaseModel`。本 Story 需确认 `app/stages/base.py` 已定义该抽象基类。
- **AD-5 索引与查询服务解耦**：确认 `app/tasks/`（Celery Worker）与 `app/pipelines/`（查询服务）目录分离。
- **AD-7 外部模型调用统一封装**：确认 `app/clients/model_client.py` 目录存在（内容由 Story 1.4 实现）。
- **AD-8 认证与鉴权统一在 API 层**：确认 `app/api/auth.py` 与 `app/api/admin/` 目录存在（内容由 Story 9.x 实现）。

### Structural Seed 对照表

| Spine 路径 | 当前路径 | 状态 |
|---|---|---|
| `backend/app/main.py` | `backend/app/main.py` | ✅ 已存在 |
| `backend/app/config.py` | `backend/app/config.py` | ✅ 已存在 |
| `backend/app/api/chat.py` | `backend/app/api/chat.py` | ✅ 已存在 |
| `backend/app/api/index.py` | `backend/app/api/index.py` | ✅ 已存在 |
| `backend/app/api/eval.py` | `backend/app/api/eval.py` | ✅ 已存在 |
| `backend/app/api/health.py` | `backend/app/api/health.py` | ✅ 已存在 |
| `backend/app/api/auth.py` | `backend/app/api/auth.py` | ✅ 已存在 |
| `backend/app/api/admin/__init__.py` | `backend/app/api/admin/` | ✅ 已存在 |
| `backend/app/api/admin/dashboard.py` | `backend/app/api/admin/dashboard.py` | ✅ 已存在 |
| `backend/app/api/admin/users.py` | `backend/app/api/admin/users.py` | ✅ 已存在 |
| `backend/app/api/admin/settings.py` | `backend/app/api/admin/settings.py` | ✅ 已存在 |
| `backend/app/api/admin/kb.py` | `backend/app/api/admin/kb.py` | ✅ 已存在 |
| `backend/app/pipelines/indexing.py` | `backend/app/pipelines/` | ✅ 已存在 |
| `backend/app/pipelines/retrieval.py` | `backend/app/pipelines/retrieval.py` | ✅ 已存在 |
| `backend/app/pipelines/generation.py` | `backend/app/pipelines/generation.py` | ✅ 已存在 |
| `backend/app/stages/base.py` | `backend/app/stages/base.py` | ✅ 已存在 |
| `backend/app/stages/parsing.py` | `backend/app/stages/parsing.py` | ✅ 已存在 |
| `backend/app/stages/chunking.py` | `backend/app/stages/chunking.py` | ✅ 已存在 |
| `backend/app/stages/embedding.py` | `backend/app/stages/embedding.py` | ✅ 已存在 |
| `backend/app/stages/vector_retrieval.py` | `backend/app/stages/vector_retrieval.py` | ✅ 已存在 |
| `backend/app/stages/bm25.py` | `backend/app/stages/bm25_retrieval.py` | ⚠️ 名称不一致，需确认 |
| `backend/app/stages/hybrid_fusion.py` | `backend/app/stages/hybrid_fusion.py` | ✅ 已存在 |
| `backend/app/stages/reranking.py` | `backend/app/stages/reranking.py` | ✅ 已存在 |
| `backend/app/stages/query_rewrite.py` | `backend/app/stages/query_rewrite.py` | ✅ 已存在 |
| `backend/app/stages/generation_llm.py` | `backend/app/stages/generation_llm.py` | ✅ 已存在 |
| `backend/app/stages/citation_parser.py` | `backend/app/stages/citation_parser.py` | ✅ 已存在 |
| `backend/app/stages/adapters/lc_retrieval.py` | `backend/app/stages/adapters/` | ✅ 目录存在 |
| `backend/app/stages/adapters/lc_generation.py` | `backend/app/stages/adapters/` | ✅ 目录存在 |
| `backend/app/stages/adapters/li_parsing.py` | `backend/app/stages/adapters/` | ✅ 目录存在 |
| `backend/app/stores/milvus.py` | `backend/app/stores/milvus.py` | ✅ 已存在 |
| `backend/app/stores/bm25_store.py` | `backend/app/stores/bm25_store.py` | ✅ 已存在 |
| `backend/app/stores/conversation.py` | `backend/app/stores/conversation.py` | ✅ 已存在 |
| `backend/app/stores/eval_results.py` | `backend/app/stores/eval_results.py` | ✅ 已存在 |
| `backend/app/stores/user.py` | `backend/app/stores/user.py` | ✅ 已存在 |
| `backend/app/stores/kb_directory.py` | `backend/app/stores/kb.py` | ⚠️ 文件名不一致 |
| `backend/app/stores/kb_file.py` | `backend/app/stores/kb.py` | ⚠️ 文件名不一致 |
| `backend/app/stores/system_setting.py` | `backend/app/stores/settings.py` | ⚠️ 文件名不一致 |
| `backend/app/models/schemas.py` | `backend/app/models/schemas.py` | ✅ 已存在 |
| `backend/app/services/chat_service.py` | `backend/app/services/chat_service.py` | ✅ 已存在 |
| `backend/app/services/index_service.py` | `backend/app/services/index_service.py` | ✅ 已存在 |
| `backend/app/services/auth_service.py` | `backend/app/services/auth_service.py` | ✅ 已存在 |
| `backend/app/services/admin_dashboard.py` | `backend/app/services/admin_dashboard.py` | ✅ 已存在 |
| `backend/app/services/kb_service.py` | `backend/app/services/kb_service.py` | ✅ 已存在 |
| `backend/app/tasks/indexing.py` | `backend/app/tasks/indexing.py` | ✅ 已存在 |
| `backend/app/clients/model_client.py` | `backend/app/clients/model_client.py` | ✅ 已存在 |
| `backend/eval/eval_set.json` | `backend/eval/` | ✅ 目录存在 |
| `backend/eval/run_eval.py` | `backend/eval/run_eval.py` | ✅ 已存在 |
| `backend/eval/metrics.py` | `backend/eval/metrics.py` | ✅ 已存在 |
| `backend/data/` | `backend/data/` | ✅ 已存在 |

> **说明**：Spine 中的部分文件名与现有实现有偏差（如 `bm25.py` vs `bm25_retrieval.py`、`kb_directory.py`/`kb_file.py` vs `kb.py`）。本 Story 不需要强制重命名已有文件，但需在核验报告中记录这些差异，并确认它们不会破坏 Spine 的模块职责划分。

---

## Technical Requirements

### 必须完成的检查项

1. **目录结构完整性**
   - [ ] 确认 `backend/app/{api,pipelines,stages/adapters,stores,models,services,tasks,clients}` 全部存在。
   - [ ] 确认 `backend/eval/` 与 `backend/data/` 存在。
   - [ ] 确认 `backend/tests/` 存在，且 `conftest.py` 已配置（若不存在则创建）。

2. **pyproject.toml 正确性**
   - [ ] `requires-python` 为 `>=3.11`。
   - [ ] 包含 FastAPI、uvicorn、Pydantic、Pydantic-Settings、Celery、Redis、SQLAlchemy、PyMySQL、pymilvus、rank-bm25、jieba、httpx、sse-starlette、structlog、python-json-logger、tenacity、bcrypt、python-jose、python-multipart。
   - [ ] 包含可选解析依赖：pypdf、python-docx、openpyxl、pypdfium2、pillow、python-frontmatter。
   - [ ] 包含评测依赖：ragas、numpy、pandas、tiktoken。
   - [ ] 包含 LangChain / LlamaIndex 生态：langchain、langchain-community、langchain-openai、llama-index。
   - [ ] 包含 Agentic RAG 依赖：langgraph、langgraph-checkpoint、langgraph-checkpoint-sqlite。
   - [ ] `[project.optional-dependencies]` 中包含 `graphrag = ["neo4j>=5.20"]`。
   - [ ] `[tool.ruff]` 配置与 project-context.md 一致：target-version="py311"、line-length=100、select=["E","F","I","N","W","UP"]、ignore=["E501"]。
   - [ ] `[tool.pytest.ini_options]` 配置与 project-context.md 一致：asyncio_mode="auto"、testpaths=["tests"]。
   - [ ] 依赖版本与现有代码实际 import 一致。

3. **关键入口文件存在性**
   - [ ] `backend/app/__init__.py` 为空或仅包含版本信息。
   - [ ] `backend/app/main.py` 可导入并启动 FastAPI 应用。
   - [ ] `backend/app/celery_app.py` 可导入并创建 Celery 应用。
   - [ ] `backend/app/config.py` 使用 Pydantic v2 Settings 从 `.env` 加载配置。

4. **.env 模板与读取**
   - [ ] 项目根目录存在 `.env`（开发环境已配置）。
   - [ ] （可选但推荐）创建/更新 `.env.example`，列出所有配置项模板。

### 明确不做

- 不实现具体业务逻辑（如 ChatService、IndexService 等）。
- 不修改现有代码的行为，除非为了修复结构不一致导致的启动失败。
- 不编写前端代码。

---

## Testing Requirements

- **单元测试**：
  - 运行 `cd backend && uv run ruff check .` 应通过（或仅存在与本 Story 无关的历史问题）。
  - 运行 `cd backend && uv run pytest` 应能发现测试目录并执行（允许部分测试因依赖服务未启动而跳过/失败）。
- **结构测试**（可新增）：
  - 编写一个轻量测试 `tests/test_project_structure.py`，断言关键目录与文件存在。该测试应通过。
- **启动测试**：
  - 在 `.env` 配置正确且依赖服务（Milvus/Redis/MySQL）已启动的前提下，`uv run uvicorn app.main:app --host 0.0.0.0 --port 8001` 应能正常启动。

---

## Project Context Reference

以下规则来自 `_bmad-output/project-context.md`，Dev Agent 必须遵守：

- **Python 版本**：>=3.11，使用 tomllib / 新 typing 语法（`str | None`、`list[float]`）。
- **Pydantic v2**：使用 `BaseModel`、`SettingsConfigDict`、`SecretStr`；禁止 v1 写法（`class Config`、`Field(..., env=)`）。
- **Stage 契约**：所有 Stage 输入/输出必须是 `pydantic.BaseModel`，实现 `AbstractStage[InputT, OutputT]`。
- **配置读取**：业务代码运行期生效的值必须走 `SettingsService.get_runtime_value()`，禁止直接读 `get_settings()` 的业务字段（启动期一次性读取的连接/端口类除外）。
- **路径**：使用 `pathlib.Path`；时间元数据统一 `datetime.utcnow().isoformat()`。
- **日志**：只走 `structlog.get_logger()`，事件名作首参、上下文字段用 kwargs；禁止 print、f-string 拼日志。
- **测试**：外部依赖一律用 `unittest.mock.MagicMock/patch` 替换；不得触碰真实 Milvus/MySQL/Redis/DashScope。

---

## Git Intelligence

最近 10 条 commit：

```
319429c angetic rag
7650be3 angetic rag
1be1172 bugfix
1d7cd70 系统设置优化
e324432 bugfix
a58fabf 文档上传支持pdf，docx，Excel
b3724d0 文档上传支持pdf，docx，Excel
fb78925 bugfix
c5aac12 首页改成异步
a38eacb lock
```

**解读**：
- 项目已深度开发，最近工作集中在 Agentic RAG、系统设置、文档上传（PDF/DOCX/Excel）、首页异步化。
- 这意味着本 Story 的"初始化后端结构"工作大部分已完成，本 Story 的核心价值是**结构核验与收尾对齐**。
- Dev Agent 不应重写已有代码，而应：
  1. 检查是否有遗漏目录/文件；
  2. 确保 `pyproject.toml` 与当前代码依赖一致；
  3. 添加轻量的结构测试；
  4. 输出核验报告。

---

## Implementation Notes for Dev Agent

### 建议的执行步骤

1. **读取当前结构**
   - 列出 `backend/` 下所有目录与关键文件。
   - 对比本 Story 的 Structural Seed 对照表。

2. **补齐缺失项**
   - 若 `backend/tests/conftest.py` 不存在，创建它（参考 project-context.md：把 backend 根目录插入 `sys.path`，提供 autouse fixture）。
   - 若 `.env.example` 不存在或过时，更新它。
   - 若 `backend/app/__init__.py` 缺失，创建空文件。

3. **校验 pyproject.toml**
   - 对照本 Story 的"pyproject.toml 正确性"检查项逐项确认。
   - 特别注意 `langgraph` 相关依赖是否已加入主依赖（当前 `pyproject.toml` 已包含，需确认版本合理）。
   - 确认 `[tool.ruff]` 和 `[tool.pytest.ini_options]` 与 project-context 一致。

4. **新增结构测试**
   - 在 `backend/tests/test_project_structure.py` 中写入断言：
     - 关键目录存在。
     - `pyproject.toml` 可解析。
     - `app.main:app`、`app.celery_app:celery_app`、`app.config:get_settings` 可导入。

5. **运行检查**
   - `uv run ruff check .`
   - `uv run pytest tests/test_project_structure.py`

6. **输出核验报告**
   - 在 story 文件末尾或单独 `1-1-init-backend-project-structure.report.md` 中记录：
     - 已存在的内容；
     - 补齐的内容；
     - 与 Spine 不一致但保留的命名（如 `bm25_retrieval.py`、`kb.py`）；
     - 检查命令的输出结果。

### 需要特别注意的地方

- **不要删除或重命名已有文件**，除非该文件的存在明确破坏了项目启动。命名差异（如 `kb.py` 合并了 `kb_directory.py` 和 `kb_file.py` 的职责）是合理的工程简化，记录即可。
- **不要修改业务逻辑**：本 Story 只关心"能不能 import"、"目录在不在"、"依赖全不全"。
- **环境变量**：`backend/.env` 已存在，Dev Agent 只需读取，不要覆盖真实密钥。

---

## Completion Status

- **Status**: ready-for-dev
- **Note**: Ultimate context engine analysis completed - comprehensive developer guide created. This story focuses on scaffold verification and alignment with Architecture Spine, since the project already has a mature backend implementation.

---

## Open Questions / Notes

1. 是否需要把 `.env.example` 从 `backend/` 移动到项目根目录？当前 `app/config.py` 从 `backend/.env` 读取，与 CLAUDE.md 中"`.env` 位于项目根目录（非 backend/）"的描述不一致。若移动，需同步修改 `config.py` 的 `_PROJECT_ROOT` 解析逻辑。
2. `backend/app/stores/kb.py` 是否同时承担了 `kb_directory` 和 `kb_file` 两个职责？若是，是否需要在未来拆分？本 Story 不处理，但需记录。
3. `backend/app/stages/bm25_retrieval.py` 与 Spine 中的 `bm25.py` 命名差异，是否需要在后续重构中统一？本 Story 仅记录。
