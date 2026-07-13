# Phase 3 子方案：多知识库扩展决策与架构

## 1. 业务触发条件与决策标准

### 1.1 何时需要第二个知识库

以下任一条件达到时，应启动多知识库拆分评估：

| 触发条件 | 判定标准 | 说明 |
|---|---|---|
| 内容边界分化 | 出现两套以上语义隔离、受众不同、更新周期差异明显的文档域 | 例如：内部运维手册 vs. 客户交付项目文档，两者用户群体与术语体系差异大 |
| 检索质量下降 | 单库场景下 RAGAS `context_precision` / `answer_relevancy` 连续下降超过 15% | 噪声文档相互污染，导致向量空间中相似但主题无关的 chunk 被召回 |
| 权限隔离需求 | 业务方要求某类文档仅对特定角色可见 | 当前目录树无权限字段，无法通过目录实现强隔离 |
| 索引稳定性问题 | 单文件增量索引或全量重建耗时超过业务容忍阈值（如 >10 分钟） | 拆库后可将 rebuild 范围限定到单个知识库，降低变更爆炸半径 |
| GraphRAG schema 冲突 | 不同目录的实体/关系类型定义相互矛盾 | 当前 GraphRAG 已按 `KbDirectory` 维护 schema，拆库可彻底隔离图模型 |

### 1.2 何时需要第三个知识库

在第二个知识库上线并稳定运行后，满足以下条件之一可考虑继续扩展：

- **业务域进一步细分**：例如将“客户交付文档”拆分为“金融行业客户”与“互联网客户”
- **性能瓶颈显现**：单个 Milvus collection 的 chunk 数量预计超过 100 万条，或 BM25 加载内存超过 2 GB
- **合规要求**：不同知识库需要独立的审计日志、保留策略或数据驻留要求
- **A/B 实验需求**：需要为新 schema 或新 parser 建立独立实验库而不影响生产库

### 1.3 暂缓扩展的信号

- 当前文档总量 < 1 万 chunk，且检索质量稳定
- 所有文档共享同一用户群体与权限策略
- 团队尚无精力维护跨库查询、去重与权限过滤逻辑

---

## 2. 知识库隔离策略

当前代码状态：系统只有“一个全局活跃索引”（`IndexMetadata.is_active=True` 唯一），Milvus collection 命名为 `cloudbrief_chunks_{timestamp}_{uuid}`，BM25 文件命名为 `bm25_index_{timestamp}_{uuid}.pkl`，GraphRAG 已按 `KbDirectory` 隔离（`kb_id=str(directory_id)`）。

建议以**顶层目录（`KbDirectory`，`parent_id=None`）**作为“知识库”边界，原因：

- 目录树已天然承载业务分类
- GraphRAG schema 已绑定 `directory_id`
- 文件物理路径为 `data/kb/dir_{directory_id}/...`，source_id 已包含 `kb/dir_{id}/` 前缀
- 避免引入新的“知识库”实体造成概念冗余

### 2.1 存储层隔离

#### Milvus collection

- 命名：`cloudbrief_kb_{kb_id}_{timestamp}_{uuid}`
- 每个知识库独立 collection，schema 与现有字段保持一致
- 保留 `source_id` 字段，便于从 chunk 反查所属目录与文件

#### BM25 索引

- 文件路径：`data/bm25/bm25_kb_{kb_id}_{timestamp}_{uuid}.pkl`
- 每个知识库独立一份 BM25 索引，避免不同术语域相互干扰
- 现有 `BM25Store` 无需改动，仅通过路径参数切换

#### MySQL 表

需做以下演进（通过 Alembic 或新增迁移脚本）：

| 表 | 改动 | 说明 |
|---|---|---|
| `index_metadata` | 新增 `kb_id: String(64)` | 标记该索引属于哪个知识库；`is_active` 改为与 `kb_id` 联合唯一，即每个 kb 有且仅有一个 active 索引 |
| `kb_directories` | 新增 `kb_type: String(16)` 或保留现状 | 顶层目录默认即为一个知识库 |
| 新增 `kb_user_access` | `kb_id`, `user_id`, `role_in_kb` | 记录用户可见知识库；admin 可访问全部 |
| `graph_shadow_records` | 已有 `kb_id` 字段，无需改动 | 继续按 `kb_id=directory_id` 记录 |

#### Redis key

- 分布式锁：`index:active_switch_lock:{kb_id}`
- 最近任务：`index:recent_tasks:{kb_id}`
- SSE 频道：`index:task:{task_id}` 保持不变，任务本身已包含 `kb_id` 上下文

### 2.2 索引元数据模型调整

`IndexMetadataStore` 从全局单活跃改为按知识库活跃：

```python
# 伪代码
def get_active(kb_id: str) -> IndexMetadata | None:
    return session.query(IndexMetadata).filter_by(kb_id=kb_id, is_active=True).first()

def switch_active(kb_id: str, collection_name: str, bm25_index_path: str) -> int:
    session.query(IndexMetadata).filter_by(kb_id=kb_id, is_active=True).update({"is_active": False})
    new_meta = IndexMetadata(kb_id=kb_id, collection_name=..., bm25_index_path=..., is_active=True)
    ...
```

---

## 3. 查询路由与分发策略

### 3.1 查询入口扩展

`ChatRequest` 增加可选字段：

```python
class ChatRequest(BaseModel):
    conversation_id: str | None = None
    question: str = ...
    stream: bool = True
    kb_ids: list[str] | None = None   # 为空表示“自动”或“全部可见”
```

前端聊天组件增加知识库选择器（支持单选/多选/全部），并遵循“新增页面必须支持双主题”的现有要求。

### 3.2 路由策略

| 模式 | 触发条件 | 行为 |
|---|---|---|
| 单库路由 | `kb_ids` 仅含一个 id | 直接查询该库的活跃 collection + BM25 |
| 自动路由 | `kb_ids` 为空 | 根据用户历史或查询分类模型自动推断最相关 1-2 个库；MVP 可降级为“全部可见库” |
| 跨库聚合 | `kb_ids` 含多个 id | 并行检索各库，再全局 RRF 融合、全局 Rerank |

### 3.3 跨库召回与去重

`RetrievalPipeline` 需要支持两种执行路径：

1. 单库路径（与现有流程基本兼容）：
   - `MilvusStore(uri, active.collection_name)`
   - `BM25Store(active.bm25_index_path)`
   - Vector + BM25 → RRF(k=60) → Rerank

2. 跨库路径：
   - 对每个 `kb_id` 并行执行上述单库路径的前三步，得到各库的 Top-K
   - 全局去重：以 `chunk_id` 为 key，同一 chunk 只保留一份（因为不同库之间不应重复，但若存在迁移场景需处理）
   - 全局 RRF：使用统一的 `k=60` 对跨库结果重新融合
   - 全局 Rerank：`RerankingStage` 接收合并后的候选集，调用 DashScope / 本地 reranker 得到最终 Top-N
   - 返回结果中保留 `source_id` 以便 `ChatService._derive_kb_id()` 继续工作

去重与相关性阈值：

- 跨库 RRF 后，若全局最高分低于 `refusal_threshold`（当前默认 0.3），仍走硬分支拒答
- 各库单独检索的 `top_k` 建议取最终 `top_n` 的 3-5 倍，避免早期截断导致全局最优结果丢失
- 若不同库对同一问题召回相同 chunk，按最高 RRF 分数保留

### 3.4 GraphRAG 路由

`ChatService._fetch_graph_context(question, kb_id)` 已按单个 `kb_id` 查询。跨库场景下：

- MVP：选择得分最高的 chunk 所属 `kb_id` 作为图上下文来源
- 完整方案：允许每个库返回图上下文后由 LLM 自行融合；需评估 token 成本与延迟

---

## 4. 索引与存储成本估算

以当前默认配置为基准：

- Embedding 模型：`text-embedding-v3`，维度 `1536`
- 每个 chunk 向量大小：1536 × 4 字节 ≈ 6 KB
- Milvus IVF_FLAT 索引额外占用约原始向量 1-2 倍
- BM25 内存占用约为原始文本的 1-3 倍（依赖分词后词项规模）

### 4.1 单库规模参考

| 指标 | 估算值 | 说明 |
|---|---|---|
| 1 个 chunk | ~6 KB 向量 + ~2 KB 文本 | 含 payload 字段 |
| 1 万个 chunk | ~80 MB 向量 + 20 MB payload | Milvus 实际占用约 150-250 MB |
| 10 万个 chunk | ~800 MB 向量 + 200 MB payload | 建议单库上限参考 |
| 100 万个 chunk | ~8 GB 向量 + 2 GB payload | 需考虑 collection 分片或拆分 |

### 4.2 多库增量成本

- 每新增一个知识库，首次全量重建成本与单库相同
- 日常单文件索引（`index_file_task`）只影响目标库，copy-on-write 会复制该库现有 chunk，**不会**复制其他库数据
- GraphRAG 图构建按库独立，Neo4j 中节点/边可通过 `kb_id` 属性或独立 label 前缀隔离

### 4.3 成本决策阈值

| 场景 | 建议 |
|---|---|
| 总 chunk < 5 万 | 保持单库，仅做逻辑隔离准备 |
| 5 万 - 20 万 | 允许 2-3 个知识库，按业务域拆分 |
| > 20 万或单库 > 10 万 | 必须拆分，并考虑 Milvus partition 或 collection 级别拆分 |
| 高并发查询 | 跨库查询会并发访问多个 collection，需监控 Milvus 连接数与延迟 |

---

## 5. 权限与数据安全

### 5.1 可见范围模型

建议采用“知识库级 ACL”：

- `admin`：全部知识库，可创建/删除/配置
- `qa`：被授权的知识库，可评测与查看后台
- `user`：被授权的知识库，仅可问答

新增表 `kb_user_access`：

```sql
CREATE TABLE kb_user_access (
    id INT PRIMARY KEY AUTO_INCREMENT,
    kb_id VARCHAR(64) NOT NULL,          -- 对应 KbDirectory.id
    user_id INT NOT NULL,
    created_by INT,
    created_at DATETIME DEFAULT NOW(),
    UNIQUE KEY uix_kb_user_access (kb_id, user_id)
);
```

### 5.2 检索权限过滤

- 路由层在解析 `kb_ids` 后，必须 intersect 用户可见库列表
- 管理员提问未指定库时，默认在全部库中检索
- 普通用户未指定库时，仅在已授权库中检索
- 即使模型意外召回未授权库的 chunk，也要在返回前做最终过滤

### 5.3 索引构建权限

- 全量重建按库触发：`POST /admin/kb/{kb_id}/rebuild`
- 仅对该库有管理权限的用户可触发
- 原有全局 `POST /index/rebuild` 在迁移期保留为“重建默认库”，过渡期后下线

---

## 6. 实施路径

### 6.1 MVP 方案（推荐先落地）

目标：支持“第二个知识库”存在并独立索引，同时保留现有首页聊天体验不变。

1. **数据模型迁移**
   - `index_metadata` 表增加 `kb_id` 字段
   - 现有记录回填 `kb_id="default"` 或第一个顶层目录 id
   - 新增 `kb_user_access` 表

2. **索引构建改造**
   - `rebuild_index_task` 支持 `kb_id` 参数，默认读取该库下所有文件
   - `index_file_task` 根据文件所在顶层目录确定 `kb_id`
   - 索引命名加入 `kb_id`
   - Redis 锁改为按 `kb_id` 加锁

3. **检索改造**
   - `RetrievalPipeline` 增加 `kb_id` 参数
   - 单库路径保持与现有流程一致
   - `ChatRequest` 增加 `kb_ids` 字段，但首页默认不传，走默认库

4. **权限与 API**
   - 管理后台新增“知识库权限”页面
   - 聊天接口校验用户可见库

5. **前端**
   - 聊天页面增加知识库选择器（支持单选）
   - 新增页面同时支持明亮/暗黑模式

### 6.2 完整方案

在 MVP 稳定后实施：

1. **跨库并行检索**
   - `RetrievalPipeline` 支持 `kb_ids: list[str]`
   - 使用线程池并发查询多个 Milvus collection 与 BM25
   - 全局 RRF + 全局 Rerank

2. **自动路由**
   - 基于查询改写或轻量分类模型，自动选择最相关知识库
   - 可结合 GraphRAG 的实体类型做意图匹配

3. **独立运行期配置**
   - 每个知识库可配置自己的 `refusal_threshold`、`embedding_model`、`graphrag_enabled` 等
   - 新增 `kb_settings` 表或按 `kb_id` 前缀存储于 `system_settings`

4. **监控与审计**
   - Dashboard 按库展示索引状态、检索量、GraphRAG shadow 报告
   - 操作日志记录按库触发 rebuild 的用户

---

## 7. 风险与回滚策略

| 风险 | 影响 | 缓解与回滚 |
|---|---|---|
| 索引命名变更导致旧索引无法加载 | 检索失败 | 迁移脚本自动回填 `kb_id`；保留旧 collection 至少一个版本；回滚时切换回旧 `IndexMetadata` 记录 |
| 跨库查询并发数过高 | Milvus/Redis 连接耗尽 | 限制用户同时可选库数量（如最多 3 个）；为每个库维护连接池；超时降级为单库 |
| 权限过滤遗漏 | 数据泄露 | 在 `RetrievalPipeline` 返回层和 `ChatService` 层双重过滤；增加审计日志 |
| 单文件索引时 copy-on-write 复制全库 | 大库增量变慢 | 未来可考虑 Milvus partition 或 upsert 替代全量重写；MVP 阶段控制单库规模 |
| 多库 RRF/Rerank 分数不可比 | 结果质量下降 | 先在各库内归一化分数，再做跨库 RRF；reranker 全局打分天然可比 |
| GraphRAG 按库隔离不彻底 | 图谱污染 | Neo4j 中节点/边增加 `kb_id` 属性，查询时带属性过滤；或采用独立 label 前缀 |
| 前端知识库选择器破坏现有首页布局 | 体验回退 | 使用 feature flag 控制；默认不展示，管理员开启后可见 |

### 回滚开关

- 环境变量/运行期配置 `MULTI_KB_ENABLED=false` 时，系统退化为当前单库行为
- `IndexMetadataStore.get_active()` 在 `kb_id` 未指定时回退到全局 `is_active=True` 记录
- 保留旧版 `rebuild_index_task` 签名兼容至少两个迭代周期

---

## 结论

建议**立即启动 MVP**：将现有顶层目录定义为知识库，把 `IndexMetadata` 从“全局单活跃”演进为“按库活跃”，先支持第二知识库的独立索引与单库查询。跨库并行召回、自动路由与细粒度权限作为完整方案在 MVP 验证后分批上线。该路径能最大限度复用现有目录树、GraphRAG schema、source_id 推导逻辑与 copy-on-write 索引机制，避免推倒重来。
