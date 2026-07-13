# Phase 3 子方案：增量更新机制完善

## 1. 当前增量能力现状

当前系统已实现以下索引更新能力：

| 能力 | 实现位置 | 说明 |
|---|---|---|
| 全量重建 | `rebuild_index_task` | 解析 `backend/data/` + `data/kb/` 全部文件，新建 collection / BM25，原子切换。 |
| 单文件增量索引 | `index_file_task` | 解析单个知识库文件，采用 **copy-on-write** 方式：加载当前活跃索引全部 chunk → 按 `source_id` 去重替换 → 写入新 collection + BM25 → `IndexMetadataStore.switch_active` 原子切换。 |
| 原子切换 | `IndexMetadataStore.switch_active` | Redis 分布式锁 `index:active_switch_lock` 保护，DB 中仅一条 `is_active=True`。 |
| 图索引增量 | `index_file_graph_task` | 文件向量索引完成后，按 `doc_id` 触发图索引增量：先删除旧 doc 的实体/关系，再写入新抽取结果。 |
| 文件状态 | `KbFile.status` | 当前枚举：`uploaded` / `indexing` / `indexed` / `failed`。 |
| 内容指纹 | `KbFile.content_hash` | 上传时计算 SHA-256，但目前仅用于记录，未参与变更检测与去重。 |

**已具备的核心优势**：COW 切换保证了索引替换期间查询不中断；单文件索引失败不会影响既有索引；图索引与向量索引解耦，可独立增量更新。

---

## 2. 缺失能力识别

### 2.1 文件级生命周期缺口

| 操作 | 当前行为 | 问题 |
|---|---|---|
| **文件替换/编辑** | 无对应接口 | 管理员只能删除后重新上传，破坏历史、引用与权限上下文。 |
| **文件删除** | `KbService.delete_file` 仅删除磁盘与 DB 记录 | 已删除文件的 chunk 仍残留在活跃 Milvus collection 与 BM25 索引中，造成“幽灵结果”。 |
| **目录删除** | 级联删除文件记录 | 同样未清理对应 chunk，且大量 chunk 失效后没有批量重建机制。 |

### 2.2 Chunk 级更新粒度不足

当前 `index_file_task` 以 **source_id（即文件粒度）** 进行整体替换，无法做到：

- 仅重新索引发生变化的部分 chunk；
- 保留未变更 chunk 的向量，减少 Embedding 调用成本；
- 对 JSON/CSV 等多行文件进行行级 diff。

> **本期定位**：在文件级 COW 替换基础上，补充 **内容指纹检测** 与 **source_id 级 tombstone（删除标记）**；真正的 chunk 级 diff 可作为后续优化项记录。

### 2.3 重复触发与幂等性缺陷

- `trigger_file_index` 仅校验 `status == "indexing"`，但若 Celery 任务实际已失败/丢失，状态可能永远卡在 `indexing`。
- 上传自动触发（`auto_index_on_upload`）未做任何幂等校验，快速连续上传/点击会导致并发 COW 切换，可能丢失中间更新。
- 同一文件的多次替换之间没有版本序列号，切换顺序无法保证。

### 2.4 版本控制与回滚缺失

- `IndexMetadata` 只有 `id`、`collection_name`、`bm25_index_path`、`is_active`、`created_at`，没有：
  - 版本号（单调递增）
  - 父版本指针
  - 变更原因（rebuild / file_add / file_replace / file_delete / rollback）
  - 受影响的 source_id 列表
- 一旦新索引上线后发现污染或抽取异常，只能重新触发全量重建，无法秒级回滚到上一版本。

### 2.5 与现有接口的耦合

- `delete_file` / `delete_directory` 是同步接口，若索引数据量大，同步 COW 重建会导致 HTTP 超时。
- 缺少“索引清理任务”的 SSE 事件流，前端无法展示删除/替换进度。

---

## 3. 增量更新流程设计

### 3.1 总体原则

1. **所有会改变索引内容的操作都走异步 Celery + SSE**：上传、替换、删除、目录删除均不阻塞 HTTP。
2. **继续采用 copy-on-write**：新索引写完后原子切换，旧 collection / BM25 文件保留一段时间供回滚。
3. **source_id 是变更的最小单元**：对知识库文件而言，`source_id` 与相对路径绑定，替换文件时尽量保持 `stored_name` 不变以复用 source_id；若 stored_name 变化，则按新增/删除处理。
4. **内容指纹优先**：内容 hash 未变化时直接跳过索引任务，避免无意义开销。

### 3.2 文件替换流程

```text
管理员上传新文件（同名覆盖）或调用 PUT /kb/files/{file_id}
  │
  ▼
KbService.replace_file(file_id, new_upload)
  ├─ 校验原文件存在
  ├─ 校验新文件类型/大小
  ├─ 计算新 content_hash
  ├─ 若 content_hash == 旧 content_hash → 直接返回“无变更”
  ├─ 写入磁盘（覆盖原 stored_name 或生成新的 stored_name，建议保持原 stored_name）
  ├─ 更新 DB：status = "uploaded", content_hash = new_hash
  └─ 触发 index_file_task(file_id, operation="replace")
       │
       ▼
index_file_task(file_id, operation="replace")
  ├─ 解析新文件 → new_chunks / new_embeddings
  ├─ 加载活跃索引全部 chunk
  ├─ 按 source_id 去重替换
  │    （若 stored_name 不变：替换同 source_id 旧 chunk
  │     若 stored_name 改变：旧 source_id chunk 标记为删除 + 新 source_id chunk 写入）
  ├─ 写入新 collection + BM25
  ├─ 原子切换，IndexMetadata 记录变更原因与受影响 source_id
  ├─ 触发图索引增量更新（同原逻辑）
  └─ 更新 KbFile.status = "indexed", last_indexed_at
```

### 3.3 文件删除流程

```text
管理员调用 DELETE /kb/files/{file_id}
  │
  ▼
KbService.delete_file(file_id, async_cleanup=True)
  ├─ 获取原文件，记录 source_id 列表
  ├─ 软删除 DB 记录：status = "deleting", deleted_at = now
  ├─ 删除磁盘文件
  └─ 触发 delete_file_index_task(file_id, source_ids)
       │
       ▼
delete_file_index_task(file_id, source_ids)
  ├─ 加载活跃索引全部 chunk
  ├─ 过滤掉 source_ids 对应的所有 chunk
  ├─ 写入新 collection + BM25
  ├─ 原子切换，IndexMetadata 记录变更原因与受影响 source_id
  ├─ 触发图索引删除：delete_doc_graph_task(kb_id, source_id)
  └─ 硬删除 DB 记录 或保留 tombstone（status = "deleted"）
```

### 3.4 目录删除流程

```text
管理员调用 DELETE /kb/directories/{directory_id}
  │
  ▼
KbService.delete_directory(directory_id)
  ├─ 收集目录及子目录下所有 file_id / source_id
  ├─ 软删除文件记录：status = "deleting"
  ├─ 删除磁盘文件与目录
  └─ 触发 delete_sources_index_task(source_ids[])
       │
       ▼
delete_sources_index_task(source_ids[])
  ├─ 加载活跃索引全部 chunk
  ├─ 批量过滤 source_ids
  ├─ 写入新 collection + BM25
  ├─ 原子切换
  ├─ 对每个 source_id 触发图索引删除
  └─ 硬删除文件/目录 DB 记录
```

### 3.5 原子切换增强

在 `IndexMetadataStore.switch_active` 中增加版本链：

```python
new_meta = IndexMetadata(
    collection_name=collection_name,
    bm25_index_path=bm25_index_path,
    is_active=True,
    version=latest_version + 1,
    parent_id=current_active.id,
    reason=reason,              # rebuild | file_add | file_replace | file_delete | rollback
    source_changes_json=json.dumps(changed_source_ids),
)
```

切换前必须校验：

- `lock` 已获取；
- 新 collection 的向量维度与当前运行时 `embedding_dim` 一致；
- 新 BM25 文件存在且非空；
- version 单调递增（乐观锁，防止并发切换覆盖）。

---

## 4. 状态机与幂等性

### 4.1 KbFile 状态机

新增 `deleting` / `deleted` 状态，完整状态机如下：

```text
                    ┌─────────────┐
         ┌─────────│   uploaded  │◄─────────┐
         │         └──────┬──────┘          │
         │                │ trigger_index    │ replace/upload new version
         │                ▼                  │
         │         ┌─────────────┐          │
         │    ┌───►│   indexing  │────┐     │
         │    │    └─────────────┘    │     │
  skip   │    │           │           │     │
 (hash   │    │ fail      │ success   │     │
unchanged)│    ▼           ▼           ▼     │
         │ ┌───────┐   ┌────────┐ ┌───────┐ │
         └─┤ failed│   │ indexed│ │deleting│ │
           └───┬───┘   └───┬────┘ └───┬───┘ │
               └───────────┘          │     │
                                     ▼     │
                                 ┌───────┐ │
                                 │deleted│ │
                                 └───────┘ │
```

- `uploaded`：文件已落盘，等待索引。
- `indexing`：Celery 任务已分发，正在构建新索引。
- `indexed`：索引已切换生效。
- `failed`：本次索引失败，不影响旧索引。
- `deleting`：已发起删除清理任务，索引侧尚未完成 COW 移除。
- `deleted`：索引与 DB 均已清理（或保留 tombstone）。

### 4.2 幂等性保障

#### 4.2.1 内容指纹去重

- 上传/替换时比较 `KbFile.content_hash`；
- 若 hash 相同且 `status == "indexed"`，直接返回成功，不触发任务；
- 若 hash 相同但 `status != "indexed"`，仅修正状态并返回，不重新 Embedding。

#### 4.2.2 并发锁

引入两层锁：

1. **文件级锁**：Redis 锁 `index:file:{file_id}`，timeout=3600s，blocking_timeout=10s。
   - `index_file_task` 与 `delete_file_index_task` 开始前获取；
   - 防止同一文件的上传/替换/删除并发执行。
2. **索引切换锁**：保留现有 `index:active_switch_lock`。

#### 4.2.3 任务状态 freshness 校验

触发新任务前：

```python
def _is_task_still_running(task_id: str | None) -> bool:
    if not task_id:
        return False
    result = AsyncResult(task_id, app=celery_app)
    return result.status in {"PENDING", "STARTED", "RETRY"}
```

- 若 `status == "indexing"` 但 Celery 状态已失败或未知，允许重新触发并覆盖状态；
- 否则返回 `409 FILE_ALREADY_INDEXING`。

### 4.3 删除幂等与清理

- 文件删除任务完成后，保留 `deleted` 状态记录 7 天（可配置），便于审计与回滚追踪；
- 物理磁盘文件在发起删除时即删除，避免空间占用；
- DB tombstone 定期由后台清理任务物理清除。

---

## 5. 与现有上传/编辑/删除接口的集成点

### 5.1 上传接口（`POST /kb/files`）

改动点：

- 计算 `content_hash` 后，检查同目录下是否已有相同 `content_hash` 的文件；
  - 若存在且已 indexed：返回已有文件引用，避免重复索引（可选，按产品决策）。
- 自动触发 `index_file_task` 前，先获取文件级锁；
- 触发后 `status = "indexing"`。

### 5.2 新增替换接口（`PUT /kb/files/{file_id}`）

新增 API：

```python
@router.put("/files/{file_id}", response_model=KbFileUploadResponse)
async def replace_kb_file(
    file_id: int,
    file: UploadFile = File(...),
    service: KbService = Depends(get_kb_service),
    current_user: UserOut = Depends(require_role("admin")),
):
    ...
```

- 默认保持 `stored_name` 不变，从而保持 `source_id` 不变；
- 若文件名后缀改变，可生成新的 `stored_name`，但旧 source_id 的 chunk 需作为删除处理。

### 5.3 删除接口（`DELETE /kb/files/{file_id}`）

改动点：

- 不立即硬删除 DB，改为软删除：`status = "deleting"`；
- 触发 `delete_file_index_task`；
- 任务成功后转为 `status = "deleted"` 或物理删除；
- 返回 `task_id`，前端可监听 SSE。

### 5.4 目录删除接口（`DELETE /kb/directories/{directory_id}`）

改动点：

- 先批量将文件状态置为 `deleting`；
- 异步触发 `delete_sources_index_task`；
- 任务成功后物理级联删除目录与文件记录。

### 5.5 手动索引接口（`POST /kb/files/{file_id}/index`）

改动点：

- 增加 freshness 校验，允许状态卡死时重新触发；
- 增加文件级锁。

### 5.6 GraphRAG 联动

- 文件替换/删除任务完成后，沿用现有 `index_file_graph_task` 或新增 `delete_doc_graph_task`；
- 删除时图索引侧必须先移除 `source_id` 对应实体与关系，避免查询到已删除内容。

---

## 6. 版本控制与回滚方案

### 6.1 IndexMetadata 版本链

扩展 `IndexMetadata` 表：

```sql
ALTER TABLE index_metadata
  ADD COLUMN version INT NOT NULL DEFAULT 1,
  ADD COLUMN parent_id INT NULL,
  ADD COLUMN reason VARCHAR(32) NULL,
  ADD COLUMN source_changes_json TEXT NULL,
  ADD INDEX idx_version (version),
  ADD INDEX idx_parent_id (parent_id);
```

版本链示例：

| id | version | parent_id | reason | source_changes_json | is_active |
|---|---|---|---|---|---|
| 10 | 5 | 9 | file_replace | `["kb/dir_3/file_a.md"]` | True |
| 9 | 4 | 8 | file_add | `["kb/dir_3/file_b.md"]` | False |
| 8 | 3 | 7 | rebuild | `[]` | False |

### 6.2 回滚流程

新增接口：`POST /admin/index/rollback/{version}` 或 `POST /admin/index/rollback`（回滚到上一个版本）。

```python
def rollback_to_version(target_version: int):
    # 1. 校验目标版本存在且不是当前 active
    target = metadata_store.get_by_version(target_version)
    current = metadata_store.get_active()
    if not target or target.id == current.id:
        raise ValueError("INVALID_ROLLBACK_TARGET")

    # 2. 校验目标 collection 与 bm25 文件仍然存在
    if not milvus_store.collection_exists(target.collection_name): raise
    if not Path(target.bm25_index_path).exists(): raise

    # 3. 获取锁，切换 active
    metadata_store.switch_active(
        collection_name=target.collection_name,
        bm25_index_path=target.bm25_index_path,
        reason="rollback",
        source_changes_json=json.dumps([]),
    )

    # 4. 记录审计日志
    logger.info("index_rolled_back", from_version=current.version, to_version=target.version)
```

**约束**：

- 回滚只回滚索引版本，不回滚文件内容本身；
- 若回滚目标版本的 `embedding_dim` 与当前设置不一致，应拒绝回滚并提示重建；
- 回滚后，之前的“最新版本”变为 inactive，但数据保留，可再次 forward rollback（即重新切回）。

### 6.3 历史版本清理策略

- 默认保留最近 10 个活跃版本 + 最近 30 天内的版本；
- 清理时仅删除 DB 元数据与 BM25 文件，Milvus collection 删除需异步执行（避免阻塞）；
- 当前 `is_active=True` 的版本以及被任何版本链引用的版本禁止清理。

---

## 7. 实施步骤与验收标准

### 7.1 实施步骤

#### 步骤 1：数据库 Schema 迁移

- [ ] 扩展 `index_metadata`：新增 `version`、`parent_id`、`reason`、`source_changes_json`。
- [ ] 扩展 `kb_files`：新增 `deleted_at`（或 `version` / `previous_hash`），调整 `status` 枚举兼容 `deleting` / `deleted`。
- [ ] 为已有记录回填 `version`：按 `created_at` 排序生成单调版本号。

#### 步骤 2：元数据层增强

- [ ] 修改 `IndexMetadataStore`：
  - `get_active()` 不变；
  - `switch_active()` 增加版本链写入；
  - 新增 `get_by_version(version)`、`list_history(limit)`、`cleanup_old_versions()`。
- [ ] 修改 `KbStore`：
  - 新增 `soft_delete_file`、`hard_delete_file`、`mark_deleting`、`list_deleting_files`；
  - `update_file_index_status` 支持 `deleted` 状态；
  - 新增按 `content_hash` 查询同目录文件。

#### 步骤 3：BM25 / Milvus 存储支持

- [ ] 验证 `BM25Store.build_index` 支持删除 chunk 后重建；
- [ ] `MilvusStore` 新增 `collection_exists` 辅助方法（或复用 `has_collection`）；
- [ ] 确保 `get_all_chunks` 在大数据量下稳定（已分页）。

#### 步骤 4：新增/改造 Celery 任务

- [ ] 改造 `index_file_task`：
  - 支持 `operation` 参数（`add` / `replace`）；
  - 接入文件级锁与 freshness 校验；
  - 写入 `IndexMetadata` 时携带 reason 与 source_changes。
- [ ] 新增 `delete_file_index_task(file_id, source_ids)`：
  - COW 移除指定 source_id；
  - 成功后软/硬删除文件记录。
- [ ] 新增 `delete_sources_index_task(source_ids[])`：
  - 用于目录删除批量清理；
  - 联动图索引删除。

#### 步骤 5：Service 层集成

- [ ] `KbService.upload_file`：加锁、去重、自动触发索引。
- [ ] 新增 `KbService.replace_file`：内容指纹检测、保持 source_id、触发替换任务。
- [ ] 改造 `KbService.delete_file`：软删除 + 异步清理。
- [ ] 改造 `KbService.delete_directory`：批量软删除 + 异步批量清理。
- [ ] `IndexService`：新增 `trigger_file_delete`、`trigger_sources_delete`、`trigger_rollback`。

#### 步骤 6：API 层

- [ ] 新增 `PUT /admin/kb/files/{file_id}` 替换接口。
- [ ] 改造 `DELETE /admin/kb/files/{file_id}` 返回 `task_id`。
- [ ] 改造 `DELETE /admin/kb/directories/{directory_id}` 返回 `task_id`。
- [ ] 新增 `POST /admin/index/rollback/{version}` 回滚接口。
- [ ] 所有新增/改造接口保持 admin 权限校验与统一错误码。

#### 步骤 7：GraphRAG 联动

- [ ] 文件替换后继续触发 `index_file_graph_task`；
- [ ] 文件/目录删除后触发图索引删除（新增 `delete_doc_graph_task` 或在 `GraphStore` 中扩展 `delete_entities_and_relations_by_doc` 批量接口）。

#### 步骤 8：测试

- [ ] 单元测试：内容指纹去重、版本链写入、回滚逻辑、状态机转换。
- [ ] 集成测试：上传 → 查询 → 替换 → 查询 → 删除 → 查询，验证 chunk 可见性变化。
- [ ] 并发测试：同一文件连续上传/替换/删除，验证锁与最终一致性。
- [ ] 回滚测试：切换到旧版本后，查询结果回退到旧索引。

#### 步骤 9：前端适配（可选但建议）

- [ ] 文件列表展示 `status` 与 `last_indexed_at`；
- [ ] 替换文件入口与进度监听；
- [ ] 删除操作展示清理任务进度；
- [ ] 后台新增“索引版本历史”与“回滚”页面。

---

### 7.2 验收标准

| 编号 | 验收项 | 通过标准 |
|---|---|---|
| A1 | 文件替换 | 调用替换接口后，新内容可被检索，旧内容不可被检索，SSE 展示完整进度。 |
| A2 | 文件删除 | 删除文件后，其 chunk 不再出现在检索结果中；图索引中对应实体/关系被清除。 |
| A3 | 目录删除 | 删除目录后，其下所有文件的 chunk 从索引中批量移除，不阻塞 HTTP。 |
| A4 | 内容指纹去重 | 上传/替换相同内容文件时，不触发新的 Embedding 与 COW 切换。 |
| A5 | 并发安全 | 同一文件的多次替换/删除/索引操作串行执行，无丢失更新。 |
| A6 | 状态机完整 | `uploaded` → `indexing` → `indexed` / `failed` / `deleting` → `deleted` 转换正确。 |
| A7 | 版本链 | `IndexMetadata` 按顺序生成版本号，保留父指针与变更原因。 |
| A8 | 回滚 | 可回滚到任意历史版本，回滚后检索结果立即恢复；回滚操作本身也生成新版本节点。 |
| A9 | 清理 | 过期版本元数据与 BM25 文件可被清理，当前活跃版本不可被清理。 |
| A10 | 监控 | 所有增量任务（包括删除/替换）均产生 SSE 事件并持久化到 `index_task_steps`。 |

---

## 8. 风险与注意事项

1. **回滚与文件内容不一致**：IndexMetadata 回滚只影响索引，不影响磁盘文件。若管理员在回滚前已替换文件内容，回滚后索引内容将与磁盘内容不一致。建议在回滚接口文档中明确约束。
2. **大目录删除性能**：目录下文件极多时，一次性加载全部 chunk 再过滤可能耗时较长。可考虑分批过滤 + 按文件分批触发删除任务（但会破坏原子性，需权衡）。
3. **GraphRAG 删除一致性**：图索引删除是异步任务，删除文件后到图数据清理完成前，图谱问答可能仍返回已删除内容。可在查询层增加 `source_id` 存在性校验。
4. **source_id 稳定性**：替换时务必保持 `stored_name` 不变，否则旧 source_id 的 chunk 残留会导致重复结果。若必须改名，需在替换任务中显式删除旧 source_id。
5. **存储成本**：COW 会保留多个 collection 与 BM25 文件，需配合版本清理策略控制 Milvus 磁盘占用。
