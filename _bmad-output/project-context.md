---
project_name: 'knowledgeAgents (CloudBrief 支持副驾)'
user_name: 'Yechen'
date: '2026-07-16'
sections_completed: ['technology_stack', 'language_rules', 'framework_rules', 'testing_rules', 'code_quality_rules', 'workflow_rules', 'critical_rules']
existing_patterns_found: 18
status: 'complete'
rule_count: 53
optimized_for_llm: true
---

# Project Context for AI Agents

_This file contains critical rules and patterns that AI agents must follow when implementing code in this project. Focus on unobvious details that agents might otherwise miss._

---

## Technology Stack & Versions

### 后端（backend/，uv 管理）
- Python >=3.11（ruff target py311；依赖 tomllib / 新 typing 语法）
- FastAPI >=0.111 + uvicorn[standard] >=0.30；pydantic >=2.7 + pydantic-settings >=2.2（v2 API）
- Celery >=5.3 + redis >=5.0（broker/backend）；SQLAlchemy >=2.0 + PyMySQL；pymilvus >=2.3
- rank-bm25 >=0.2.2 + jieba（中文分词稀疏检索）；httpx >=0.27；sse-starlette >=2.1
- structlog >=24.1 + python-json-logger（JSON 结构化日志）；tenacity（重试）
- python-jose[cryptography] >=3.3（JWT）；bcrypt >=4.1,<5.0.0（显式钉住 <5，勿升级）
- 解析：pypdf、pypdfium2、python-docx、openpyxl、pillow、python-frontmatter
- ragas >=0.1（评测）；numpy、pandas、tiktoken
- 适配器（可选路径）：langchain >=0.2 + langchain-community + langchain-openai；llama-index >=0.10
- 可选 extra `graphrag`：neo4j >=5.20
- 模型服务：DashScope（text-embedding-v3 / qwen3-rerank / qwen3.7-plus），可切本地 vLLM/Ollama

### 前端（frontend/，npm 管理）
- Next.js ^14.2（App Router，非 15）+ React ^18.3 + TypeScript ^5.4（strict: true）
- Tailwind CSS ^3.4 + next-themes ^0.4.6（明暗双主题）
- lucide-react（图标）、cytoscape（图谱可视化）、react-syntax-highlighter、@llamaindex/ui
- eslint ^8.57 + eslint-config-next ^14.2.35

### 基础设施（docker compose，非标本地端口避免冲突）
- Milvus 2.3.x → :19531；Redis 7 → :6381；MySQL 8 → :3307；MinIO Console → :9003
- 可选 vLLM reranker profile → :8000（`docker compose --profile reranker up -d`）
- FastAPI 默认 :8001；Next.js 默认 :3000（占用时自动 3001）

### 工具链
- 后端：uv（`uv sync`）、ruff（line-length 100，select E,F,I,N,W,UP，ignore E501）、pytest（asyncio_mode=auto）
- 前端：npm、next lint

## Critical Implementation Rules

### Language-Specific Rules

**Python（后端）**
- 一律使用 Pydantic v2 API：`BaseModel`、`SettingsConfigDict`、`SecretStr`；禁止 v1 写法（`class Config`、`Field(..., env=)`）
- 所有 Stage 输入/输出必须是 `pydantic.BaseModel` DTO，实现 `AbstractStage[InputT, OutputT]`；Stage 之间只通过 DTO 传递，禁止共享可变对象（AD-1）
- 同步/异步分工：CPU 型 Stage（parsing/chunking/bm25/fusion）用同步 `execute()`；涉及 LLM/网络 I/O 的 Stage（generation_llm 等）用 `async def execute()` / `execute_stream()`；Service 层一律 async
- 日志只走 `structlog.get_logger()`，事件名作首参、上下文字段用 kwargs（如 `logger.info("chat_request", user_id=...)`）；禁止 print、f-string 拼日志
- 路径拼接只用 `pathlib.Path`；时间元数据统一 `datetime.utcnow().isoformat()`（ISO 8601 UTC，与既有代码一致）
- 配置只从 `app.config.get_settings()`（lru_cache 单例）读取；禁止硬编码密钥/URL/模型名
- 现代类型语法：`str | None`、`list[float]`

**TypeScript（前端）**
- `strict: true`：禁止隐式 any；共享类型集中在 `lib/types.ts`，角色用字面量联合 `'admin' | 'qa' | 'user'`
- 路径别名 `@/*` → 项目根（如 `@/lib/auth`），禁止深层相对路径 `../../../`
- 交互组件文件顶部必须有 `'use client'`；组件约定为 `export default function ComponentName(props)` + 独立 `*Props` interface
- API 调用统一经 `lib/auth.ts` 的 `authFetch`（自动带 token/credentials）；错误读取统一响应结构 `err.error?.message`
- 所有 fetch 响应先判 `res.ok`，失败时 `res.json().catch(() => ({}))` 兜底再抛错

### Framework-Specific Rules

**FastAPI（后端）**
- 路由用 `APIRouter(tags=[...])`，统一在 `main.py` 中 `include_router`；管理接口聚合在 `api/admin/` 的 admin_router
- 接口出入参 DTO 一律定义在 `app/models/schemas.py`，禁止在路由内联定义
- 鉴权只在 API 层：严格接口 `Depends(get_current_user)`，匿名兼容接口 `Depends(get_current_user_optional)`，角色校验 `Depends(require_role("admin", ...))`；Service/Store 层禁止碰 token（AD-8）
- token 三通道读取顺序：Bearer Header → `access_token` Cookie → `?token=` query（SSE 无法自定义 Header，必须保留此兼容）
- 同步 DB/存储调用在 async 路由里用 `asyncio.to_thread` 包装，避免阻塞事件循环
- SSE 响应：`StreamingResponse(..., media_type="text/event-stream")` + 固定头 `Cache-Control: no-cache`、`Connection: keep-alive`、`X-Accel-Buffering: no`；事件格式 `event: {type}\ndata: {json(ensure_ascii=False)}\n\n`
- 错误统一 `raise HTTPException(status_code=..., detail=...)`，由全局处理器塑形为 `{error: {code, message, detail}}`
- 跨请求共享的重资源（如 GraphStore）挂 `app.state`，通过 Depends 工厂函数注入（参考 `get_chat_service`）

**Celery（异步任务）**
- 队列名固定：`kb.index.rebuild`、`kb.index.single`、`kb.graph.rebuild`；新任务必须显式路由到对应队列
- 每阶段进度通过 Redis Pub/Sub 发布事件（step/status/duration_ms/log/timestamp），由 `/index/tasks/{id}/events` SSE 端点消费

**Next.js 14 / React（前端）**
- App Router：页面在 `app/`，管理页在 `app/admin/*`；`middleware.ts` 校验 `access_token` Cookie 并重定向 `/admin/login`，新增管理页自动受保护
- 主题：`app/providers.tsx` 的 ThemeProvider（next-themes）已在根 layout 挂载；所有 UI 必须用语义化 Tailwind 变量（`bg-card`、`text-card-foreground`、`border`、`dark:*`），禁止写死颜色，新增 UI 必须同时适配明暗两套变量
- 管理后台页面复用 `components/AdminLayout.tsx` 框架
- 图标一律用 lucide-react
- 流式/任务进度状态收敛在 hooks（`useTaskStream` 轮询+SSE 混合、`useIndexRebuild`），组件只消费 hook 返回值，不自行管理 EventSource

### Testing Rules
- pytest：`asyncio_mode = "auto"`（async 测试无需装饰器）、`testpaths = ["tests"]`；测试文件命名 `test_<模块名>.py`，与被测模块一一对应
- `tests/conftest.py` 把 backend 根目录插入 `sys.path`，测试直接 `import app.*`；含 autouse fixture，新增测试文件无需重复配置
- 外部依赖（Store、ModelClient、Celery app）一律用 `unittest.mock.MagicMock/patch` 替换；测试不得触碰真实 Milvus/MySQL/Redis/DashScope
- DTO 直接构造（如 `Document(..., updated_at=datetime.utcnow(), ...)`）；文件系统场景用 `tmp_path`；PDF 测试用 reportlab 现造（dev 依赖）
- 提交前跑 `uv run pytest` + `uv run ruff check .`；单文件调试 `uv run pytest tests/test_x.py`

### Code Quality & Style Rules
- ruff：line-length 100，select `E,F,I,N,W,UP`，ignore `E501`；前端用 eslint-config-next
- 命名：模块/目录 snake_case；类名 `*Stage` / `*Pipeline` / `*Store` / `*Service`；DTO 后缀 `*Input` / `*Output` / `*Result`；前端组件 PascalCase.tsx、hooks `use*.ts`
- ID 约定：chunk_id = `{source_type}:{source_id}:{chunk_index}`（引用解析与增量索引依赖此格式）；会话 UUID v4；任务 ID 用 Celery task id；用户 ID 自增 int
- 角色枚举固定 `admin / qa / user`，禁止自定义角色；密码只存 bcrypt 哈希，禁止明文、禁止入日志
- 注释/文档字符串用中文，简洁且只在非显而易见处书写（与既有代码风格一致）

### Development Workflow Rules
- 无 CI 流水线：合并前本地必须跑通 `uv run pytest`、`uv run ruff check .`、`npm run lint`
- Git 提交信息为简短自由格式（中文可），无 conventional commits 约束
- `.env`、`.venv`、`.next`、`node_modules` 已 gitignore，禁止提交；`.env` 位于项目根目录（非 backend/）
- 本地启动顺序：`docker compose up -d` → 后端 `uv sync` → uvicorn(:8001) → Celery worker（必须 `-Q kb.index.rebuild,kb.index.single,kb.graph.rebuild`）→ 前端 `npm run dev`
- 首次问答前必须重建一次索引（前端按钮或 `POST /index/rebuild`），否则 `RetrievalPipeline` 抛 `No active index found`
- 后台「系统设置」修改持久化到 `system_settings` 表；注意设置项上的 `restart_required` / `requires_reindex` 标记，改动后按标记执行重启或重建索引

### Critical Don't-Miss Rules
- AD-2：生成阶段的唯一知识来源是 `RetrievalResult`；LLM/GenerationPipeline 禁止直接接触 Milvus、BM25 索引或原始文件
- AD-3：拒答是 LLM 调用之前的硬分支（`max_score < refusal_threshold`，默认 0.3）；禁止"低分也先让 LLM 试试"
- AD-5：查询服务对索引只读；索引写入只发生在 Celery Worker；活跃索引切换走 `IndexMetadataStore.switch_active`（Redis 分布式锁保护）原子完成；单文件索引用 copy-on-write 合并后切换
- DashScope embedding 单批上限 10 条（`embedding_batch_size = 10`），超过会直接调用失败
- RRF 融合固定 `k=60`；不要在 Stage 里静默改这个常量
- Reranker 不可用时自动回退到融合分数（HybridFusion score），不要把本地 reranker 故障变成硬失败
- 密钥（`DASHSCOPE_API_KEY` 等）只经 `get_settings()` 注入；禁止写进代码、日志或提交；settings API 对 secret 字段做掩码
- 本地端口非标准：Milvus 19531 / Redis 6381 / MySQL 3307 / 后端 8001；写脚本或文档时禁止套用默认端口
- `bcrypt` 钉在 `<5.0.0`，升级会破坏现有密码哈希兼容，勿动
- 前端：禁止写死颜色（必须明暗双主题变量）；禁止在组件里直接管理 EventSource（走 hooks）

---

## Usage Guidelines

**For AI Agents:**

- Read this file before implementing any code
- Follow ALL rules exactly as documented
- When in doubt, prefer the more restrictive option
- Update this file if new patterns emerge

**For Humans:**

- Keep this file lean and focused on agent needs
- Update when technology stack changes
- Review quarterly for outdated rules
- Remove rules that become obvious over time

Last Updated: 2026-07-16
