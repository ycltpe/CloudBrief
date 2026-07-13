# Phase 3 实施路线图：评估与扩展

**项目**：CloudBrief 支持副驾（Enterprise RAG）  
**阶段**：Phase 3 — 评估与扩展  
**周期**：2–4 周  
**制定日期**：2026-07-13  
**依赖前提**：Phase 1（异步索引与实时日志）、Phase 2（GraphRAG 图索引与生成增强）已完成并上线。

---

## 1. 执行摘要

Phase 3 的目标是在真实流量中验证系统质量，并为下一阶段的规模化做准备。本阶段围绕四条主线展开：

1. **真实用户查询抽样评估**：建立可持续的 RAG 质量度量体系。
2. **多知识库扩展决策**：从单一知识库演进为支持第二、第三个知识库的架构。
3. **增量更新机制完善**：补齐文件替换、删除、版本回滚与幂等性。
4. **监控与 Fallback 机制**：构建生产级可观测性与分级降级能力。

**建议推进顺序**：

- **第 1 周**：优先落地监控与 Fallback（低风险、快速止血），同步启动查询日志采集。
- **第 2 周**：完成自动/人工评估流水线，开始积累真实样本。
- **第 3 周**：启动多知识库 MVP（按顶层目录定义知识库）和增量更新改造。
- **第 4 周**：联调、压测、验收，输出 Phase 3 复盘与 Phase 4 规划。

> 若资源受限，可压缩为 2 周：只做监控 Fallback + 查询日志 + 评估 MVP，将多知识库与增量更新延后到 Phase 4。

---

## 2. 范围与边界

### 2.1 在本阶段内完成

- 核心监控指标埋点、`/metrics` 暴露、基础告警规则。
- 模型/Milvus/LLM 超时等关键 Fallback 路径。
- 查询日志采集、`query_logs` 表与自动评估流水线。
- 管理后台 eval 标注界面增强与 Dashboard 指标看板。
- 多知识库架构决策与 MVP 实现（按 `KbDirectory` 拆分，支持第二知识库独立索引与单库查询）。
- 增量更新改造：文件替换、文件删除、目录删除、版本链与回滚。

### 2.2 不在本阶段内（建议 Phase 4）

- 跨库并行检索与全局 Rerank（完整方案）。
- 自动知识库路由/意图分类。
- 细粒度知识库级运行期配置（每个库独立 embedding_model / refusal_threshold）。
- OpenTelemetry 全链路 Tracing（可选，视排障需求）。
- 大规模 Milvus partition/collection 分片优化。

---

## 3. 关键决策建议

| 决策点 | 建议方案 | 理由 |
|---|---|---|
| 知识库边界 | 以顶层 `KbDirectory` 作为知识库 | 复用现有目录树、GraphRAG schema、source_id 推导逻辑 |
| 索引活跃模型 | 从全局单活跃改为按 `kb_id` 单活跃 | 支持各库独立重建，互不阻塞 |
| 文件替换 | 默认保持 `stored_name` 不变，保持 `source_id` 稳定 | 避免旧 chunk 残留导致重复结果 |
| 删除策略 | 软删除 + 异步 COW 清理 | 不阻塞 HTTP，支持审计与回滚追踪 |
| 版本链 | `IndexMetadata` 增加 `version`、`parent_id`、`reason` | 实现秒级回滚与变更溯源 |
| 监控基座 | Prometheus + Grafana，数据库持久化趋势 | 与现有 Docker Compose 集成最轻量 |
| 评估 judge | LLM-as-judge 自动评分 + QA 人工抽检 | 兼顾效率与可信度 |

---

## 4. 四条主线详细计划

### 4.1 真实用户查询抽样评估

**目标**：在真实流量中建立可持续的 RAG 质量评估机制。

**核心指标**：

| 维度 | 指标 |
|---|---|
| 检索 | `context_precision`、`context_recall` |
| 引用 | `citation_precision`、`citation_recall` |
| 生成 | `faithfulness`、`answer_relevance`、`completeness` |
| 拒答 | `false_refusal_rate`、`false_accept_rate` |
| 时效 | `stale_rate` |
| 性能 | `latency_total_p50/p90/p99`、`latency_stage_ms` |
| 满意度 | `human_score`、`thumbs_up_rate` |

**抽样策略**：

- 周度基线：100 条自动评估 + 50 条人工标注。
- 分层维度：问题类型、答案形态（正常/拒答/过期/GraphRAG）、用户角色、知识库目录、是否 fallback。
- 匿名化：`user_id` 加盐哈希、问题文本正则脱敏（手机/邮箱/身份证/工号）。

**关键动作**：

1. 新增 `query_logs` 表，在 `ChatService` 中异步写入完整运行时上下文与配置快照。
2. 新增 `backend/eval/real_eval.py`，周度从 `query_logs` 采样并调用 `LLMJudgeMetrics`。
3. 增强 `frontend/app/admin/eval`：多维度打分表单、citation 高亮、检索片段展示。
4. 扩展 `/admin/dashboard`：本周核心指标均值、延迟分位、拒答率、过期率。
5. 建立双周 bad case 复盘会机制。

**验收标准**：

- 100% 真实问答写入 `query_logs`，PII 合规审计通过。
- 每周一 08:00 前完成上周自动评估，关键指标缺失率 < 2%。
- QA 标注效率 ≥ 20 条/小时，双盲 Cohen's Kappa ≥ 0.75。

---

### 4.2 多知识库扩展

**目标**：支持第二、第三个知识库的独立索引与单库查询，为后续跨库检索打好基础。

**触发条件**（满足任一即可启动拆分）：

- 出现语义隔离、受众不同的文档域。
- 单库 RAGAS 指标连续下降超过 15%。
- 业务方提出权限隔离需求。
- 单库 chunk 数量预计超过 10 万或重建耗时超过业务阈值。

**MVP 实现**：

1. **数据模型**：
   - `index_metadata` 新增 `kb_id` 字段，`is_active` 改为与 `kb_id` 联合唯一。
   - 新增 `kb_user_access` 表记录用户可见库。
   - 现有记录回填 `kb_id="default"`。

2. **索引构建**：
   - `rebuild_index_task` 支持 `kb_id` 参数。
   - `index_file_task` 根据文件所在顶层目录确定 `kb_id`。
   - 索引命名加入 `kb_id`：`cloudbrief_kb_{kb_id}_{timestamp}_{uuid}`。
   - Redis 锁改为按 `kb_id` 加锁：`index:active_switch_lock:{kb_id}`。

3. **检索改造**：
   - `RetrievalPipeline` 增加 `kb_id` 参数。
   - `ChatRequest` 增加可选 `kb_ids` 字段。
   - 首页默认不传，走默认库，保持现有体验。

4. **权限与 API**：
   - 聊天接口校验用户可见库列表。
   - 新增 `/admin/kb/{kb_id}/rebuild`。
   - 管理后台新增知识库权限配置页。

5. **前端**：
   - 聊天页面增加知识库选择器（单选）。
   - 新增页面同时支持明亮/暗黑模式。

**验收标准**：

- 第二知识库可独立上传、索引、查询，不影响默认库。
- 权限过滤生效：普通用户无法检索未授权库。
- 设置 `MULTI_KB_ENABLED=false` 时系统退化为当前单库行为。

---

### 4.3 增量更新机制完善

**目标**：补齐文件替换、删除、版本回滚与幂等性，避免“幽灵结果”和重复索引。

**现状与缺口**：

- 已支持：全量重建、单文件 COW 增量索引、图索引增量。
- 缺失：文件替换/编辑接口、文件删除后索引清理、chunk 级变更检测、版本回滚、并发幂等。

**核心设计**：

1. **所有变更操作异步化**：上传、替换、删除、目录删除均走 Celery + SSE。
2. **内容指纹去重**：`KbFile.content_hash` 未变化时跳过索引任务。
3. **source_id 级 tombstone**：删除文件时按 `source_id` 过滤 chunk。
4. **版本链**：`IndexMetadata` 增加 `version`、`parent_id`、`reason`、`source_changes_json`，支持秒级回滚。
5. **两层锁**：
   - 文件级锁 `index:file:{file_id}`：防止同一文件并发上传/替换/删除。
   - 切换锁 `index:active_switch_lock:{kb_id}`：保留现有原子切换语义。

**新增/改造任务**：

| 任务 | 说明 |
|---|---|
| `index_file_task` | 增加 `operation` 参数（`add`/`replace`），保持 `source_id` 稳定 |
| `delete_file_index_task` | COW 移除指定 source_id，完成后物理/软删除文件 |
| `delete_sources_index_task` | 目录删除时批量清理多个 source_id |
| `rollback_to_version` | 回滚到任意历史版本索引 |

**新增 API**：

- `PUT /admin/kb/files/{file_id}`：替换文件。
- `DELETE /admin/kb/files/{file_id}`：返回 `task_id`，异步清理索引。
- `DELETE /admin/kb/directories/{directory_id}`：返回 `task_id`，批量清理。
- `POST /admin/index/rollback/{version}`：回滚到指定版本。

**验收标准**：

- 文件替换后新内容可检索、旧内容不可检索。
- 文件/目录删除后对应 chunk 不再出现在检索结果中。
- 上传相同内容文件不触发新的 Embedding 与 COW 切换。
- 同一文件并发操作串行执行，无丢失更新。
- 可回滚到任意历史版本，回滚后检索结果立即恢复。

---

### 4.4 监控与 Fallback 机制

**目标**：构建生产级可观测性，确保单点故障时能优雅降级。

**关键监控指标**：

| 类别 | 指标 |
|---|---|
| 检索 | `rag_retrieval_latency_ms`、`rag_recall_count`、`rag_rerank_max_score` |
| 生成 | `rag_generation_latency_ms`、`rag_refusal_rate` |
| 错误 | `rag_error_total`（按错误码拆分） |
| 健康 | `rag_model_up`、`rag_index_task_success_rate` |

**Fallback 策略**：

| 故障场景 | Fallback 行为 |
|---|---|
| LLM 超时/不可用 | 返回道歉文案，自动切换备用 provider |
| Reranker 失败 | 回退到 RRF 融合分数，标记 `is_fallback=true` |
| Milvus 不可用 | 降级到 BM25-only 召回 |
| BM25 也失败 | 触发硬分支拒答 |
| 无活跃索引 | 引导用户重建索引 |

**实施动作**：

1. 新增 `backend/app/metrics.py`，定义 Prometheus Registry 与核心指标。
2. 暴露 `/metrics` 路由与 `/health/models` 健康探测。
3. 在 `ModelClient`、`RetrievalPipeline`、`GenerationPipeline`、`ChatService` 中埋点。
4. 新增 MySQL `monitoring_metrics` 表用于长期趋势。
5. 补齐 `MilvusUnavailableError` 降级、LLM 超时兜底、多 provider 自动切换。
6. 提供 `infra/prometheus.yml` 与 `infra/alert_rules.yml` 示例。
7. 在 `/admin/dashboard` 增加系统健康卡片。

**验收标准**：

- 访问 `/metrics` 能看到核心指标。
- 手动关闭 Milvus 后问答仍能返回 BM25 结果并标记 fallback。
- LLM 超时后用户收到明确提示且错误码计数增加。
- Prometheus + Grafana 可选 profile 能正常启动并展示 Dashboard。

---

## 5. 2–4 周时间线

### 第 1 周：可观测与止血

| 天数 | 任务 | 负责模块 |
|---|---|---|
| 1–2 | 新增 `app/metrics.py`、Prometheus Registry、`/metrics` 路由 | 监控 |
| 1–2 | 在 ModelClient / RetrievalPipeline / GenerationPipeline 埋点 | 监控 |
| 2–3 | 实现 LLM 超时兜底、Milvus 降级 BM25、Reranker fallback 指标 | Fallback |
| 3–4 | 新增 `query_logs` 表与异步写入逻辑 | 评估 |
| 4–5 | 实现 `/health/models` 与多 provider 自动切换 | Fallback |
| 5 | 第一周验收：/metrics 可用、Milvus 降级验证通过 | — |

### 第 2 周：评估体系 MVP

| 天数 | 任务 | 负责模块 |
|---|---|---|
| 1–2 | 实现 `backend/eval/real_eval.py` 自动采样与 judge | 评估 |
| 2–3 | 增强 admin eval 页面：多维度标注、citation 高亮 | 评估前端 |
| 3–4 | 扩展 dashboard：本周 faithfulness、latency、拒答率、过期率 | 评估前端 |
| 4–5 | 建立标注规范、校准集与双盲流程 | 评估 |
| 5 | 第二周验收：自动评估跑通、QA 标注界面可用 | — |

### 第 3 周：多库与增量更新

| 天数 | 任务 | 负责模块 |
|---|---|---|
| 1–2 | `index_metadata` 增加 `kb_id`、版本链字段；新增 `kb_user_access` | 多库 |
| 2–3 | 改造 `rebuild_index_task` / `index_file_task` 支持 `kb_id` | 多库 |
| 2–3 | 改造 `RetrievalPipeline` 与 `ChatRequest` 支持 `kb_id` | 多库 |
| 3–4 | 实现文件替换、删除、目录删除 Celery 任务 | 增量更新 |
| 4–5 | 实现版本链写入与回滚接口 | 增量更新 |
| 5 | 第三周验收：第二知识库可独立索引、文件删除后无幽灵结果 | — |

### 第 4 周：联调、压测与复盘

| 天数 | 任务 | 负责模块 |
|---|---|---|
| 1–2 | 多库 + 增量更新联调；并发测试 | 全链路 |
| 2–3 | Dashboard 告警规则校准；Grafana 看板 final review | 监控 |
| 3–4 | 评估数据复盘：首周真实样本指标解读 | 评估 |
| 4–5 | 编写 Phase 3 复盘文档、Phase 4 规划、更新 CLAUDE.md | 文档 |
| 5 | 第四周验收：全部里程碑达成 | — |

---

## 6. 优先级与依赖

```text
监控与 Fallback（P0，第1周）
  └─ 不依赖其他主线，可立即启动
  └─ 阻塞：无

查询日志采集（P0，第1周末）
  └─ 依赖：ChatService 已有阶段输出
  └─ 阻塞：自动评估流水线

自动评估流水线（P1，第2周）
  └─ 依赖：query_logs
  └─ 阻塞：Dashboard 指标看板、bad case 复盘

多知识库 MVP（P1，第3周）
  └─ 依赖：IndexMetadata 改造
  └─ 阻塞：跨库并行检索（Phase 4）

增量更新改造（P1，第3周）
  └─ 依赖：Celery 索引任务、IndexMetadata 版本链
  └─ 可与多库 MVP 并行
```

**资源紧张时的裁剪建议**：

- 2 周版本：只做监控 Fallback + 查询日志 + 自动评估 MVP，多库与增量更新延后。
- 3 周版本：加上多库 MVP 或增量更新二选一。
- 4 周版本：完整执行本路线图。

---

## 7. 里程碑与验收标准

| 里程碑 | 时间 | 验收标准 |
|---|---|---|
| M1：监控与 Fallback 上线 | 第 1 周末 | `/metrics` 暴露核心指标；Milvus/LLM/Reranker 降级路径验证通过；Dashboard 健康卡片可用。 |
| M2：评估体系运转 | 第 2 周末 | `query_logs` 100% 覆盖真实问答；自动评估每周稳定产出；QA 标注界面可用；首周指标报告产出。 |
| M3：多知识库 MVP | 第 3 周末 | 第二知识库可独立索引与单库查询；权限过滤生效；单库行为可开关回退。 |
| M4：增量更新完善 | 第 3 周末 | 文件替换/删除/目录删除异步清理；内容指纹去重生效；版本链与回滚可用。 |
| M5：Phase 3 闭环 | 第 4 周末 | 全链路联调通过；真实样本 bad case 复盘完成；Phase 4 规划与优先级明确。 |

---

## 8. 主要风险与缓解

| 风险 | 影响 | 缓解措施 |
|---|---|---|
| 监控埋点拖慢主流程 | 延迟增加 | 指标采样异步化，数据库聚合写入走后台任务 |
| LLM judge 成本过高 | 评估费用失控 | 仅对采样样本调用完整 judge；设置超时与失败回退 |
| 多库索引命名变更导致旧索引无法加载 | 检索失败 | 迁移脚本回填 `kb_id`；保留旧 collection；提供回滚开关 |
| 跨库查询并发耗尽 Milvus 连接 | 系统不稳定 | 限制用户可选库数量；为每个库维护连接池；超时降级 |
| 文件删除后图索引清理延迟 | 返回已删除内容 | 查询层增加 `source_id` 存在性校验；删除任务完成后审计 |
| 回滚与磁盘文件不一致 | 索引与内容错位 | 回滚接口文档明确约束；管理员替换文件后谨慎回滚 |
| 隐私合规 | 数据泄露 | 入池即脱敏；哈希化用户 ID；限制 QA 访问；定期审计 |
| 标注一致性差 | 评估结果不可信 | 校准集 + Cohen's Kappa；双盲仲裁；持续迭代规范 |

---

## 9. 已确认决策

| 序号 | 决策项 | 结论 |
|---|---|---|
| 1 | 多知识库拆分时机 | **立即支持**。已明确需要服务金融、医疗、房产等多个业务域，系统必须具备可扩展的多知识库能力。 |
| 2 | 知识库访问权限 | **用户可申请，admin 审批**。普通用户默认无权限，需提交申请并由管理员审批后方可访问对应知识库。 |
| 3 | 本地备用 provider | **需要**。为 LLM 与 Reranker 准备本地 vLLM/Ollama 备用实例，作为主 provider 不可用时的 fallback。 |
| 4 | 版本保留策略 | **接受**。`IndexMetadata` 历史版本默认保留最近 10 个 + 30 天内版本。 |
| 5 | 周期裁剪 | **压缩为 2 周 MVP**。优先保证多知识库可用、监控 Fallback 兜底、查询日志与自动评估基础能力，增量更新完整版延后。 |

---

## 10. 2 周 MVP 冲刺计划

### Sprint 1（第 1 周）：多知识库核心 + 查询日志

| 天数 | 任务 | 产出 |
|---|---|---|
| 1 | `index_metadata` 增加 `kb_id`；新增 `kb_user_access` 表；数据库迁移 | Schema 就绪 |
| 1–2 | `IndexMetadataStore` 按 `kb_id` 管理活跃索引；Redis 锁按 `kb_id` 隔离 | 元数据层就绪 |
| 2–3 | `rebuild_index_task` / `index_file_task` 支持 `kb_id`，索引命名带 `kb_id` | 索引构建支持多库 |
| 3–4 | `RetrievalPipeline` / `ChatRequest` / `ChatService` 支持 `kb_id` 单库路由 | 检索支持知识库选择 |
| 4–5 | 知识库访问申请、审批、权限校验 API | 权限与申请流程可用 |
| 4–5 | 新增 `query_logs` 表，`ChatService` 异步写入运行时上下文 | 查询日志采集上线 |
| 5 | Sprint 1 验收：第二业务知识库可独立索引与单库查询 | — |

### Sprint 2（第 2 周）：监控 Fallback + 自动评估 + 管理后台

| 天数 | 任务 | 产出 |
|---|---|---|
| 1–2 | `app/metrics.py` + `/metrics` + `/health/models`；核心指标埋点 | 可观测基础 |
| 2–3 | `ModelClient` 多 provider 切换；Milvus 降级 BM25；LLM 超时兜底 | Fallback 机制 |
| 3–4 | `backend/eval/real_eval.py` 周度自动采样 judge；Celery beat 定时任务 | 自动评估流水线 |
| 4–5 | 管理后台：知识库列表/权限审批/版本历史/系统健康卡片 | 管理界面 |
| 5 | Sprint 2 验收：全链路跑通，2 周 MVP 上线 | — |

---

## 11. 下一步行动

1. ✅ 已确认 5 个决策事项，确定按 2 周 MVP 执行。
2. 立即开始 Sprint 1 开发：数据库模型改造 → 索引任务 → 检索路由 → 权限申请审批 → 查询日志。
3. 同步准备本地 provider 部署方案（vLLM/Ollama）与资源申请。
4. 每日站会同步阻塞风险；每周五进行里程碑验收。
5. 2 周 MVP 结束后输出复盘，规划 Phase 4（跨库检索、完整增量更新、A/B 实验）。

---

## 附录：子方案原文

本路线图由以下四份子方案整合而来，详细设计请参见同级目录：

- `phase3-sub-eval-real-user-queries.md` — 真实用户查询抽样评估
- `phase3-sub-multi-kb-expansion.md` — 多知识库扩展决策与架构
- `phase3-sub-incremental-update.md` — 增量更新机制完善
- `phase3-sub-monitoring-fallback.md` — 监控与 Fallback 机制
