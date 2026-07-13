# Addendum: 文件上传后异步构建索引并实时展示日志

本 addendum 收录不适合放入 Brief 正文的技术深度素材：用户故事、验收标准、API 变更、数据模型变更、前端交互、错误处理与风险缓解。

## 1. 用户故事与验收标准

### US-1：上传后自动触发索引

**作为** 管理员  
**我希望** 上传文件后系统自动开始索引  
**以便** 我无需手动点击“整合重建索引”即可让新知识可用

**验收标准：**
- [ ] `POST /admin/kb/files` 保存文件并写入 `kb_files` 表后，调用 `IndexService.trigger_file_index(file_id)`。
- [ ] 返回体包含 `file` 对象与 `task_id`。
- [ ] 若触发任务失败，文件仍被保存，但 `status=uploaded` 并记录错误日志。

### US-2：实时查看索引进度与日志

**作为** 管理员  
**我希望** 在文件列表旁看到实时索引日志  
**以便** 快速了解索引是否成功及失败原因

**验收标准：**
- [ ] 文件行显示当前 `status`（uploaded / indexing / indexed / failed）。
- [ ] 点击“查看日志”后，前端通过 `EventSource` 连接 `GET /index/tasks/{task_id}/events`。
- [ ] 日志面板按时间顺序显示 `step`、`message`、`timestamp`、`level`。
- [ ] 任务完成或失败后自动关闭连接，并展示最终状态。
- [ ] 连接断开后，前端使用 `Last-Event-ID` 自动重连并补发遗漏事件。

### US-3：保留全量重建能力

**作为** 管理员  
**我希望** 仍可手动触发整合重建索引  
**以便** 在批量更新或索引异常时刷新全库

**验收标准：**
- [ ] `POST /admin/kb/rebuild` 继续可用，调用 `KbService.trigger_rebuild()`。
- [ ] 全量重建与单文件索引使用不同 Celery 队列或分布式锁互斥，避免同时切换活跃索引。
- [ ] Dashboard 的“最近任务”列表同时展示两种任务。

### US-4：幂等上传

**作为** 系统  
**我希望** 同一文件重复上传不会重复索引  
**以便** 节省计算资源并保持向量库整洁

**验收标准：**
- [ ] 重复上传同一文件（相同 `file_id` 或相同内容 hash）触发任务但 Stage 检测到无变化时直接标记为 `indexed`。
- [ ] Milvus 中不出现重复的 chunk 向量（v1 可通过先删除旧向量再写入实现）。

## 2. API 变更

### 2.1 上传文件接口

`POST /admin/kb/files` 返回体新增 `task_id`：

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

### 2.2 触发单文件索引（新增）

`POST /admin/kb/files/{file_id}/index`（可选，用于手动重跑）

- 仅 admin 可调用。
- 返回 `{ "task_id": "..." }`。
- 若文件已在 indexing 状态，返回 409 Conflict。

### 2.3 SSE 端点（已存在，需前端接入）

`GET /index/tasks/{task_id}/events`

- 事件类型：`step`、`log`、`progress`、`complete`、`error`。
- 鉴权：通过 cookie 或 URL 短期签名 token。

## 3. 数据模型变更

### 3.1 `kb_files` 表

新增字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `status` | enum | uploaded / indexing / indexed / failed |
| `last_indexed_at` | datetime | 上次成功索引时间 |
| `last_task_id` | varchar | 最近一次索引任务 ID |
| `content_hash` | varchar | 文件内容 hash（预留，用于增量去重） |
| `index_error` | text | 最近一次失败原因 |

### 3.2 任务状态（Redis + Celery result backend）

- Celery `AsyncResult` 保存 `PENDING / STARTED / SUCCESS / FAILURE / RETRY`。
- Redis 保留步骤事件：`index:task:{task_id}:events`（list 或 stream）。
- 最近任务记录：`index:recent_tasks`（sorted set）。

## 4. 前端交互

### 4.1 文件列表

- 每行文件显示状态徽标：
  - 🟡 uploaded（已上传，未索引）
  - 🔵 indexing（索引中）
  - 🟢 indexed（已索引）
  - 🔴 failed（失败）
- 操作列增加“查看日志”按钮，仅 indexing / failed 状态显示。

### 4.2 实时日志弹窗/抽屉

- 标题：`v2.5-release-notes.md 索引日志`
- 内容：时间轴形式展示步骤事件。
- 底部：最终状态 + 耗时。
- 失败时：展示 `index_error` 与“重新索引”按钮。

### 4.3 全局开关

- 在 `/admin/settings` 增加“上传后自动构建索引”开关，默认开启。
- 关闭后，上传文件仅保存，不自动触发索引。

## 5. 错误处理

| 错误场景 | 行为 | 用户可见 |
|---|---|---|
| 文件格式不支持 | 上传接口 400，文件不保存 | “不支持的文件类型：.docx” |
| 解析失败 | 任务标记 failed，`index_error` 记录异常 | 日志面板显示失败步骤与异常信息 |
| Embedding API 超时 | Celery 自动重试 3 次，最终 failed | “Embedding 调用超时，请检查模型服务” |
| Milvus 写入失败 | 任务 failed，临时 collection 清理 | “向量写入失败，请联系管理员” |
| 并发重建冲突 | 后触发任务进入队列等待锁释放 | 日志显示“等待其他索引任务完成” |

## 6. 性能与扩展

- 单文件索引任务应在 Embedding 调用耗时基础上增加不超过 20% 开销。
- 10 个并发上传不应阻塞全量重建，通过队列隔离实现。
- SSE 连接数应限制 per-user，防止浏览器连接耗尽。

## 7. 测试策略

- **单元测试**：
  - `index_file_task` 使用 `celery.contrib.pytest` + memory broker。
  - Stage 使用 mock Store 与 ModelClient。
- **集成测试**：
  - Docker Compose 中上传文件 → 触发任务 → SSE 收到完成事件 → Milvus 可检索到该文件 chunk。
- **幂等测试**：
  - 重复上传同一文件，验证向量数量不增加。
- **并发测试**：
  - 同时触发全量重建与单文件索引，验证活跃索引切换互斥。

## 8. 依赖与阻塞

- 依赖：已完成的知识库管理（目录树、文件上传、重建索引触发）。
- 阻塞：无。
- 风险：增量索引的 chunk hash diff 超出 v1 范围，v1 可先按“单文件全量替换”实现。

## 9. 决策记录

- **决策 1**：v1 不引入新消息队列，复用 Celery + Redis。理由：基础设施已就绪，降低运维复杂度。
- **决策 2**：SSE 优于 WebSocket。理由：日志/进度为单向流，SSE 更简单且后端端点已存在。
- **决策 3**：保留手动全量重建。理由：批量更新与兜底恢复仍需要。
- **决策 4**：v1 增量策略为“单文件全量替换”，不实现 chunk hash diff。理由：控制范围，后续 Phase 2 再引入精细增量。
