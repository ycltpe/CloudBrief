---
name: 文件上传后异步构建索引并实时展示日志
altitude: feature
purpose: design-record
status: final
created: 2026-07-06
updated: 2026-07-06
paradigm: 事件驱动异步任务 + SSE 实时推送
scope: 知识库文件上传后的自动索引与实时日志展示
sources:
  - _bmad-output/planning-artifacts/briefs/brief-knowledgeAgents-2026-07-06/brief.md
  - _bmad-output/planning-artifacts/briefs/brief-knowledgeAgents-2026-07-06/addendum.md
  - _bmad-output/planning-artifacts/research/technical-file-upload-async-index-build-realtime-logs-research-2026-07-05.md
  - _bmad-output/planning-artifacts/architecture/architecture-knowledgeAgents-2026-07-02/ARCHITECTURE-SPINE.md
companions: []
---

# Architecture — 文件上传后异步构建索引并实时展示日志

## 1. Context

本架构文档是 `architecture-knowledgeAgents-2026-07-02/ARCHITECTURE-SPINE.md` 的**特性级补充**，聚焦于“文件上传后异步构建索引并实时展示日志”能力。它承接已归档的产品简报与 Brief Addendum，定义该特性在现有 CloudBrief 支持副驾系统中的结构、行为、接口与约束。

## 2. Design Paradigm

**事件驱动异步任务 + SSE 实时推送**

- 文件上传完成后产生一个领域事件（文件已持久化），由编排层将其转化为 Celery 任务。
- 索引构建在 Celery Worker 中异步执行，与 FastAPI 查询服务解耦（继承系统级 AD-5）。
- Worker 每完成一个阶段向 Redis Pub/Sub 发布事件；FastAPI SSE 端点将事件流式推送给浏览器。
- 浏览器使用原生 `EventSource` 消费事件，无需额外 WebSocket 基础设施。

## 3. High-Level Data Flow

```text
┌─────────────────┐     POST /admin/kb/files      ┌──────────────┐
│  Admin Console  │ ─────────────────────────────▶ │  FastAPI API │
│   (Next.js)     │                                  │   (Uvicorn)  │
└────────┬────────┘                                  └──────┬───────┘
         │                                                  │
         │ 2. EventSource /index/tasks/{task_id}/events     │ 1. save file
         │◀─────────────────────────────────────────────────┤    + create task
         │                                                  ▼
         │                                           ┌──────────────┐
         │                                           │   Celery     │
         │                                           │   Broker     │
         │                                           │   (Redis)    │
         │                                           └──────┬───────┘
         │                                                  │
         │ 5. SSE events                                      │ 3. dispatch
         │◀───────────────────────────────────────────────────┤
         │                                                  ▼
         │                                           ┌──────────────┐
         │                                           │ Celery Worker│
         │                                           │ index_file   │
         │                                           │ _task        │
         │                                           └──────┬───────┘
         │                                                  │
         │                                                  ▼
         │                                    ┌──────────────────────────┐
         │                                    │  Parse → Chunk → Embed   │
         │                                    │  → Write Milvus → BM25   │
         │                                    │  → Atomic Switch         │
         │                                    └───────────┬──────────────┘
         │                                                │
         │ 4. publish step events                         ▼
         │◀────────────────────────────────────────── Redis Pub/Sub
```

## 4. Component View

### 4.1 API Layer

| 组件 | 文件 | 职责 |
|---|---|---|
| `kb_router` | `backend/app/api/admin/kb.py` | 接收上传请求，保存文件，调用 `KbService.upload_file()`，返回 `file` + `task_id`。可选新增 `POST /admin/kb/files/{file_id}/index`。 |
| `index_router` | `backend/app/api/index.py` | 已提供 `GET /index/tasks/{task_id}` 与 `GET /index/tasks/{task_id}/events`。本特性复用 SSE 端点。 |

### 4.2 Service Layer

| 组件 | 文件 | 职责 |
|---|---|---|
| `KbService` | `backend/app/services/kb_service.py` | 在上传成功后调用 `IndexService.trigger_file_index(file_id)`；保留 `trigger_rebuild()` 用于全量重建。 |
| `IndexService` | `backend/app/services/index_service.py` | 新增 `trigger_file_index(file_id)` 创建 Celery 任务；`event_stream(task_id)` 订阅 Redis 并返回 SSE 流；`get_task_status(task_id)` 合并 Celery 状态与 Redis 步骤。 |

### 4.3 Task Layer

| 组件 | 文件 | 职责 |
|---|---|---|
| `index_file_task` | `backend/app/tasks/indexing.py` | 新 Celery 任务（`bind=True`）。负责编排单文件索引 Stage，捕获异常，发布步骤事件，更新 `kb_files.status`。 |
| `rebuild_index_task` | `backend/app/tasks/indexing.py` | 现有全量重建任务，保持不变，但与单文件任务使用不同队列或锁互斥。 |

### 4.4 Stage Layer

复用现有 `ARCHITECTURE-SPINE.md` 定义的 Stage 契约（AD-1）。

| Stage | 输入 | 输出 | 说明 |
|---|---|---|---|
| `ParsingStage` | `file_path: Path` | `List[Document]` | 读取 `data/kb/` 下单文件；当前 NativeParser 已支持 `data/kb`。 |
| `ChunkingStage` | `List[Document]` | `List[Chunk]` | 按配置切分文本。 |
| `EmbeddingStage` | `List[Chunk]` | `List[EmbeddingResult]` | 批量调用 `ModelClient.embed()`。 |
| `MilvusWriteStage` | `List[EmbeddingResult]` | `collection_name: str` | 写入临时 collection。 |
| `BM25BuildStage` | `List[Chunk]` | `bm25_path: str` | 构建/更新 BM25 索引文件。 |
| `AtomicSwitchStage` | `collection_name, bm25_path` | `IndexMetadata` | 原子切换活跃索引元数据。 |

### 4.5 Event & Real-Time Layer

| 组件 | 文件 | 职责 |
|---|---|---|
| `_publish_step()` | `backend/app/tasks/indexing.py` | 向 Redis 频道 `index:task:{task_id}` 发布步骤事件；使用 `setex` 保留最近事件 1 小时。 |
| `event_stream()` | `backend/app/services/index_service.py` | SSE 生成器：先推送 `_load_steps()` 历史事件，再订阅频道实时推送；监听 `request.is_disconnected()`。 |
| `EventSource` | `frontend/hooks/useTaskStream.ts` | 前端 Hook：建立 SSE 连接、处理 `step/log/progress/complete/error` 事件、自动重连。 |

### 4.6 Storage Layer

| 存储 | 用途 |
|---|---|
| MySQL (`kb_files`, `kb_directories`) | 文件元数据、索引状态、最近任务 ID。 |
| Local disk (`data/kb/`) | 原始文件与 BM25 `.pkl` 文件。 |
| Milvus | 向量索引；每次任务可写入临时 collection，切换后旧 collection 保留用于回滚。 |
| Redis | Celery broker/result、Pub/Sub 事件通道、最近任务 sorted set。 |

## 5. State Machine

### 5.1 文件索引状态（`kb_files.status`）

```text
        uploaded
           │
           │ upload_file triggers index_file_task
           ▼
        indexing ◄─────────────────┐
           │                        │
     success│              failure │
           ▼                        │
        indexed ──── (retry) ──────┘
           │
           │ delete file
           ▼
       deleted
```

- `uploaded`：文件已保存，尚未触发或触发失败。
- `indexing`：Celery 任务已派发，正在执行。
- `indexed`：索引构建成功，文件内容可被检索。
- `failed`：索引构建失败，`index_error` 记录原因。

### 5.2 任务事件类型（SSE）

| 事件 | 字段 | 含义 |
|---|---|---|
| `step` | `name`, `status`, `started_at`, `duration_ms` | 阶段开始/完成 |
| `log` | `level`, `message`, `timestamp` | 结构化日志行 |
| `progress` | `current`, `total` | 进度百分比 |
| `complete` | `result`, `duration_ms` | 任务成功完成 |
| `error` | `error`, `traceback` | 任务失败 |

## 6. Key Architectural Decisions

### AD-F1 — 单文件索引与全量重建共享 Stage，但使用独立任务入口

- **约束：** `index_file_task` 与 `rebuild_index_task` 必须复用同一套 Stage 实现，避免两套索引逻辑。
- **原因：** 减少重复代码；保证单文件与全量重建的切分、嵌入、写入行为一致。
- **代价：** 需要抽象 Stage 输入，使 `index_file_task` 的输入为单个文件路径，而 `rebuild_index_task` 的输入为目录扫描结果。

### AD-F2 — 索引事件通过 Redis Pub/Sub 广播，SSE 端点做协议转换

- **约束：** Worker 不直接向浏览器推送；浏览器不直接连接 Redis。
- **原因：** 保持 Worker 无状态；利用 FastAPI 的 HTTP/SSE 能力处理鉴权、重连、多客户端订阅。
- **风险与缓解：** Pub/Sub 消息不持久，客户端断线期间会丢失；通过 `setex` 保留最近事件并在 SSE 连接建立时补发；未来可迁移到 Redis Streams。

### AD-F3 — 单文件索引任务与全量重建任务必须互斥写入活跃索引

- **约束：** 任意时刻只能有一个任务执行 `AtomicSwitchStage`。
- **原因：** 防止并发切换导致 `index_metadata` 指向部分构建的索引，破坏查询一致性。
- **实现：** Celery 不同队列 + Redis 分布式锁（Redlock），或统一队列序列化切换操作。

### AD-F4 — 上传接口返回 `task_id` 但文件保存与任务触发解耦

- **约束：** 文件写入磁盘与数据库后，再触发 Celery 任务；触发失败不应回滚文件保存。
- **原因：** 文件是用户资产，任务失败可重试；回滚文件会导致用户需要重新上传。
- **结果：** 若触发失败，`status` 保持 `uploaded`，管理员可手动重试或重新上传。

### AD-F5 — 默认自动索引，但提供全局开关

- **约束：** 系统设置中增加 `auto_index_on_upload` 布尔值，默认 `true`。
- **原因：** 降低上线风险；管理员可在异常场景下切回手动重建模式。

## 7. API & Interface Changes

### 7.1 上传文件响应扩展

`POST /admin/kb/files`

```json
{
  "id": 42,
  "directory_id": 3,
  "original_name": "v2.5-release-notes.md",
  "stored_name": "v2_5_release_notes_abc12345.md",
  "size": 2048,
  "mime_type": "text/markdown",
  "status": "indexing",
  "created_at": "2026-07-06T10:23:00Z",
  "task_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
}
```

### 7.2 手动重跑单文件索引（可选）

`POST /admin/kb/files/{file_id}/index`

响应：

```json
{ "task_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890" }
```

### 7.3 SSE 端点（已存在）

`GET /index/tasks/{task_id}/events`

事件示例：

```text
event: step
data: {"name":"parse","status":"completed","started_at":"...","duration_ms":120}

event: log
data: {"level":"info","message":"Parsed 12 chunks","timestamp":"..."}

event: complete
data: {"duration_ms":3450,"result":{"collection":"...","bm25_path":"..."}}
```

## 8. Data Model Additions

### 8.1 `kb_files` 表扩展

```sql
ALTER TABLE kb_files ADD COLUMN status ENUM('uploaded','indexing','indexed','failed') NOT NULL DEFAULT 'uploaded';
ALTER TABLE kb_files ADD COLUMN last_indexed_at DATETIME NULL;
ALTER TABLE kb_files ADD COLUMN last_task_id VARCHAR(36) NULL;
ALTER TABLE kb_files ADD COLUMN content_hash VARCHAR(64) NULL;
ALTER TABLE kb_files ADD COLUMN index_error TEXT NULL;
```

### 8.2 Pydantic Schemas

新增/更新：

- `KbFileOut.status`：enum 字段。
- `KbFileOut.task_id`：可选字符串。
- `TaskEvent`：SSE 事件数据模型。
- `IndexFileTaskPayload`：Celery 任务参数。

## 9. Concurrency & Scalability

### 9.1 队列设计

建议配置 Celery `task_routes`：

```python
task_routes = {
    'tasks.index_file_task': {'queue': 'kb.index.single'},
    'tasks.rebuild_index_task': {'queue': 'kb.index.rebuild'},
    'tasks.maintenance.*': {'queue': 'kb.maintenance'},
}
```

- 单文件索引与全量重建分离，避免小任务被大任务阻塞。
- 同一队列内仍通过锁保证切换互斥。

### 9.2 Worker 配置

```python
celery_app.conf.update(
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_time_limit=3600,
    task_serializer='json',
    accept_content=['json'],
)
```

### 9.3 水平扩展

- FastAPI API：无状态，可部署多实例；SSE 连接需要 sticky session 或共享 Redis 事件总线（当前 Redis Pub/Sub 已满足）。
- Celery Worker：可按队列独立扩容。
- Milvus：当前单机；数据量增长后迁移到 Milvus Cluster 或 Zilliz Cloud。

## 10. Security & Compliance

### 10.1 鉴权

- 上传与索引端点沿用现有 JWT/Session 鉴权（AD-8）。
- `task_id` 与用户/租户绑定；`get_task_status`/`event_stream` 必须校验当前用户是否有权访问该任务。
- SSE 使用 cookie 鉴权；跨域场景下使用短期签名 URL token。

### 10.2 输入校验

- 文件类型、大小、文件名在上传接口校验；当前限制 `.md/.json/.csv/.txt`。
- 解析阶段对异常内容做 try/except，避免 Worker 崩溃。

### 10.3 敏感数据

- 若上传文档含 PII，应在解析/嵌入前进行脱敏或过滤（v1 不实现，但预留扩展点）。

## 11. Deployment & Operations

### 11.1 Docker Compose 服务

新增或复用 `celery_worker` 服务，建议拆分为：

- `worker-index-single`：处理 `kb.index.single` 队列。
- `worker-index-rebuild`：处理 `kb.index.rebuild` 队列。

### 11.2 监控

| 指标 | 工具 |
|---|---|
| 任务状态、Worker 负载 | Flower |
| 队列深度、任务耗时、SSE 连接数 | Prometheus + Grafana |
| 结构化日志 | structlog + Loki（可选） |

### 11.3 健康检查

- API：`GET /health` 检查 Redis、MySQL、Milvus 连通性。
- Worker：启动时检查 broker 可达性；`SIGTERM` 时完成当前任务再退出。

## 12. Testing Strategy

- **单元测试**：`index_file_task` 使用 `celery.contrib.pytest`；Stage 使用 mock Store。
- **集成测试**：Docker Compose 中跑端到端：上传 → 任务触发 → SSE 收到完成事件 → 查询命中新 chunk。
- **并发测试**：同时触发全量重建与单文件索引，验证锁互斥与元数据一致性。
- **幂等测试**：重复上传同一文件，验证向量数量不增加。

## 13. Migration & Rollout

1. **数据库迁移**：执行 `kb_files` 表字段新增。
2. **代码部署**：部署 API + Worker 新代码，不破坏现有重建索引功能。
3. **开关上线**：默认开启 `auto_index_on_upload`，观察任务成功率与队列深度。
4. **前端迁移**：先保留轮询作为 fallback，再逐步切换到 SSE。
5. **回滚**：关闭全局开关即可回到手动重建模式；旧索引元数据机制保持不变。

## 14. Open Questions & Future Work

- **Redis Streams 迁移**：当需要断线重放与消费组时，将 Pub/Sub 升级为 Streams。
- **增量 chunk diff**：Phase 2 实现 `content_hash` 与 chunk 级去重。
- **对象存储事件**：未来接入 S3/MinIO `ObjectCreated` 事件，绕过 FastAPI 上传触发。
- **死信队列**：对多次失败的任务转储到 DLQ，并提供管理界面。

## 15. References

- [ARCHITECTURE-SPINE.md](architecture-knowledgeAgents-2026-07-02/ARCHITECTURE-SPINE.md) — CloudBrief 支持副驾系统级架构
- [brief-knowledgeAgents-2026-07-06/brief.md](../briefs/brief-knowledgeAgents-2026-07-06/brief.md) — 产品简报
- [brief-knowledgeAgents-2026-07-06/addendum.md](../briefs/brief-knowledgeAgents-2026-07-06/addendum.md) — 需求与技术细节
- [technical-file-upload-async-index-build-realtime-logs-research-2026-07-05.md](../research/technical-file-upload-async-index-build-realtime-logs-research-2026-07-05.md) — 技术研究
