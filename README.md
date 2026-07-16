# CloudBrief 支持副驾

Enterprise RAG 内部知识问答系统， AI 应用工程师作品集案例。

## 系统架构

- **后端**：FastAPI + Pydantic + SQLAlchemy + Celery
- **存储**：Milvus（向量）、BM25 文件索引、MySQL（会话/元数据/评测）
- **缓存/队列**：Redis
- **模型**：DashScope text-embedding-v3 / qwen3-rerank / qwen3.7-plus，支持本地 LLM fallback
- **前端**：Next.js 14 + @llamaindex/ui
- **检索链路**：混合检索（BM25 + 向量）→ RRF(k=60) → qwen3-rerank → 带引用生成 → 硬分支拒答 → 时效提示

## 快速启动

### 1. 拉起依赖

```bash
docker compose up -d
```

本地端口映射（避免与已有项目冲突）：
- Milvus: 19531
- Redis: 6381
- MySQL: 3307
- Minio Console: 9003

### 2. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env，填入各模型组的 API Key（LLM_API_KEY 等）
```

### 3. 安装后端依赖

```bash
cd backend
uv venv --python /Users/yechen/.local/bin/python3.11
uv sync
```

### 4. 启动后端

```bash
uv run uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload
```

### 5. 启动 Celery Worker

```bash
uv run celery -A app.celery_app worker --loglevel=info
```

### 6. 启动前端

```bash
cd frontend
npm install
npm run dev
```

前端默认运行在 http://localhost:3000（若被占用则使用 3001）。

## 主题模式

前端支持明亮 / 暗黑模式切换：

- 默认跟随系统偏好（`prefers-color-scheme`）。
- 点击右上角主题图标可在明亮、暗黑之间切换。
- 用户选择后会保存在 `localStorage`，刷新页面后保持。

技术实现：

- `next-themes` 处理主题状态与持久化。
- Tailwind CSS `darkMode: 'class'` 策略。
- 全局语义化颜色变量定义在 `frontend/app/globals.css`。

- `GET /health` 健康检查
- `POST /chat` 提问
- `GET /chat/{id}` 会话历史
- `POST /index/rebuild` 异步重建索引
- `GET /index/tasks/{id}` 任务状态
- `GET /index/tasks/{id}/events` SSE 实时进度
- `GET /eval/results` 评测记录
- `GET /eval/results/{id}` 评测详情

## 评测

```bash
cd backend
uv run python -m eval.run_eval
```

## 项目结构

```
backend/
  app/
    api/            # FastAPI 路由
    clients/        # ModelClient 统一模型调用
    models/         # Pydantic DTO
    pipelines/      # Retrieval / Generation Pipeline
    services/       # ChatService / IndexService
    stages/         # Native Stage + LangChain/LlamaIndex 适配器
    stores/         # Milvus / BM25 / MySQL 封装
    tasks/          # Celery 异步任务
  eval/             # 评测集与脚本
  data/             # 合成知识库
frontend/
  app/              # Next.js 页面
  components/       # Chat / IndexRebuildPanel / AnswerWithCitations
```
