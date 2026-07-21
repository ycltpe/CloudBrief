---
stepsCompleted:
  - step-01-validate-prerequisites
  - step-02-design-epics
  - step-03-create-stories
inputDocuments:
  - _bmad-output/planning-artifacts/research/technical-agentic-rag-key-technologies-research-2026-07-15.md
  - _bmad-output/planning-artifacts/research/technical-agentic-rag-orchestration-frameworks-research-2026-07-15.md
---

# CloudBrief 支持副驾 - Agentic RAG 五能力演进 Epic Breakdown

## Overview

本文件承接 [`technical-agentic-rag-key-technologies-research-2026-07-15.md`](technical-agentic-rag-key-technologies-research-2026-07-15.md) 与 [`technical-agentic-rag-orchestration-frameworks-research-2026-07-15.md`](technical-agentic-rag-orchestration-frameworks-research-2026-07-15.md)，将「Indexing / Hybrid Search / Filtering / Scalability / 多模态 Embeddings 在 Agent 中的应用」研究结论拆分为可实施的 Epic 与 Story。

**核心设计原则:**
- 沿用项目已验证的「后台开关切流 + shadow 旁路对照 + RAGAS 回归守门」采用模式
- 五个能力按「成本升序、叙事价值降序」推进:Filtering → 观测/对照 → 工具化 → 多模态 PoC → 晚交互研究
- 检索工具化(Epic 12)与编排框架研究的 Phase 3 汇合,应合并排期
- 全部为零新增服务实现,与作品集体量匹配

---

## Epic 10: Filtering 产品化(检索期元数据过滤)

**Epic Goal:** 把已存储在 Milvus 中的元数据(source_type / title / updated_at / source_id)用起来,支持检索期过滤与受控 self-querying,替代生成后时效检查的部分场景。

### Story 10.1: 为 MilvusStore.search 增加 filter 参数

As a 检索系统，
I want 向量检索时能够传入标量过滤表达式，
So that 检索结果可以按时间、来源类型等条件预筛选。

**Acceptance Criteria:**

**Given** `MilvusStore.search()` 当前仅按 top_k 召回
**When** 扩展方法签名为 `search(query_embedding, top_k=50, filter: str | None = None)`
**Then** 当 `filter` 非空时,通过 Milvus `search(filter=...)` 传入表达式
**And** 过滤表达式字段限定白名单:`source_type`、`title`、`updated_at`、`source_id`
**And** 白名单外字段直接返回 400 `INVALID_FILTER_FIELD`
**And** 空字符串或 None 时保持现有行为不变
**And** `backend/app/stores/milvus.py` 单测覆盖 filter 传参与空值分支

### Story 10.2: 检索期时效过滤(替代生成后检查)

As a 系统，
I want 检索阶段就按 `stale_threshold_days` 过滤掉过旧片段，
So that 拒答/生成阶段不再依赖低质量的过期来源。

**Acceptance Criteria:**

**Given** `settings_service` 已提供 `stale_threshold_days` 运行期配置(默认 90 天)
**When** `RetrievalPipeline.retrieve()` 调用 `MilvusStore.search()`
**Then** 自动追加 `updated_at >= now() - stale_threshold_days` 过滤条件
**And** 过滤后空结果直接走硬分支拒答,不进入 LLM 生成
**And** 原 `CitationParserStage` 的时效检查保留作为兜底,但前端提示文案与状态保持一致
**And** RAGAS 评测集补充「时效意图」样本以度量改变

### Story 10.3: Self-Querying 白名单版(按元数据过滤)

As a Agent/高级用户，
I want 用自然语言指定来源类型或时间范围,系统自动翻译成 Milvus filter,
So that 查询意图可以更精确。

**Acceptance Criteria:**

**Given** 用户提问如"近 30 天更新日志里关于导出的说明"
**When** `SelfQueryingStage` 执行
**Then** LLM 仅被允许输出白名单内的字段与操作符(`==`、`!=`、`>`、`<`、`>=`、`<=`、`AND`、`OR`)
**And** 输出 schema 为 `{query: str, filter: str | None, reasoning: str}`
**And** 若 LLM 输出白名单外字段,直接忽略该字段并记录到 `query_logs.self_querying_dropped_field`
**And** 生成的 filter 表达式再经过一次语法白名单校验,校验失败视为空 filter
**And** 提供后台开关 `self_querying_enabled` 控制是否启用

---

## Epic 11: 级联观测与索引对照

**Epic Goal:** 让混合检索级联与索引选择的全过程可观测、可实验,用数据驱动 Indexing 策略演进(HNSW/IVF/量化对照)。

### Story 11.1: query_logs 扩列(级联全链路落盘)

As a 开发者/运维，
I want 每次问答都记录检索级联的完整中间状态，
So that 我能离线分析召回、融合、重排各环节的效果。

**Acceptance Criteria:**

**Given** 一次 `/chat` 请求完成
**When** `_log_query()` 执行
**Then** 新增以下字段(JSON 列):
  - `vector_hits`: 向量检索命中数
  - `bm25_hits`: BM25 命中数
  - `rrf_k`: 当前使用的 k 值
  - `rerank_provider`: 实际使用的重排 provider(含 fallback 标记)
  - `applied_filter`: 实际生效的 filter 表达式
  - `index_version`: 当前使用的索引版本(collection_name)
  - `index_type`: IVF_FLAT / HNSW / 其他
**And** 字段以 `query_logs.extra_json` 或独立 JSON 列存储,不破坏现有查询接口
**And** 已有测试覆盖字段写入与读取反序列化

### Story 11.2: 索引算法 Shadow 对照(HNSW vs IVF_FLAT)

As a 系统，
I want 在保留 IVF_FLAT 主路径的同时,对一定比例流量用 HNSW 索引跑 shadow 检索，
So that 用真实数据对比召回与延迟。

**Acceptance Criteria:**

**Given** 后台设置 `vector_index_type` 可选 `IVF_FLAT`(默认)或 `HNSW`,并新增 `shadow_index_type`
**When** 索引重建任务执行时
**Then** 同步构建主索引与 shadow 索引(同一 kb_id 的两个 collection),shadow 索引使用 HNSW + COSINE + 推荐默认参数(M=16, efConstruction=200)
**And** 检索请求按 `shadow_ratio`(默认 0%)切流,shadow 路径只检索不生成,结果落 `query_logs`
**And** 提供管理后台只读面板(或 CLI 脚本)对比两路:召回重叠率、P50/P95 延迟、Top-5 召回差异样本
**And** shadow 索引失败不影响主路径,不阻塞用户响应

### Story 11.3: 配置化级联参数运行期可调

As a 管理员，
I want 在后台直接调整 top_k、rrf_k、rerank_top_n、max_hops 等参数，
So that 参数实验不需要发版。

**Acceptance Criteria:**

**Given** 新增/复用 `SettingMeta` 注册项:`retrieval_top_k`、`hybrid_rrf_k`、`rerank_top_n`、`agent_max_hops`
**When** 管理员在系统设置页修改并保存
**Then** 新参数立即对后续请求生效(进程级缓存 60s TTL,与现有 settings 一致)
**And** 每次请求将参数快照写入 `query_logs.config_snapshot`
**And** 参数越界时返回明确校验错误(如 rrf_k < 1)

---

## Epic 12: 检索能力工具化(Agentic RAG 汇合点)

**Epic Goal:** 把 `RetrievalPipeline` 包装为 Agent 可调用的 tool,让 LLM/Agent 能组合 hybrid 检索、过滤、重排能力;与编排框架研究的 Phase 3 合并实现。

### Story 12.1: 定义 RetrievalTool Schema

As a Agent 编排层，
I want 一个稳定的 tool schema 来描述检索调用，
So that LangGraph/LlamaIndex/自研编排都能复用同一工具。

**Acceptance Criteria:**

**Given** 检索工具名为 `knowledge_retrieval`
**When** 定义 schema
**Then** 输入参数限定为:
  - `query: str`(必填)
  - `mode: Literal["hybrid","vector","bm25"] = "hyybrid"`
  - `top_k: int = 50`
  - `filter: str | None = None`(需先经过 10.3 白名单校验)
  - `use_rerank: bool = True`
**And** 输出 schema 复用现有 `RetrievalResult` Pydantic 列表,附加 `sources` 摘要
**And** schema 定义在 `app/tools/schemas.py`,工具实现在 `app/tools/retrieval_tool.py`
**And** 工具描述经过 prompt 工程优化,确保 Agent 知道何时调用、如何构造 filter

### Story 12.2: ModelClient 扩展 function calling

As a Agent 节点，
I want `ModelClient.chat()` 支持 `tools` 参数并正确解析 `tool_calls`，
So that Agent 能调用检索工具。

**Acceptance Criteria:**

**Given** DashScope 兼容模式支持 OpenAI 风格 function calling
**When** 扩展 `ModelClient.chat(messages, tools=None, tool_choice=None, stream=False)`
**Then** 保持现有 failover/重试/日志/超时机制不变
**And** 当响应包含 `tool_calls` 时返回结构化 `ToolCall` 列表(含 id/name/arguments)
**And** 工具结果通过 `role="tool"` 消息回传模型时,`ModelClient` 正确序列化
**And** 为工具调用单独记录 `tool_trace`(路由决策、参数、结果摘要)

### Story 12.3: 实现 Tool-Use 版 RetrievalPipeline

As a Agent，
I want 接收 LLM 的检索工具调用并执行,再把结果喂回 LLM，
So that Agent 可以自主决定检索策略。

**Acceptance Criteria:**

**Given** Agent 节点收到 `tool_calls` 中 name=`knowledge_retrieval`
**When** `ToolNode` 或等效执行器解析参数
**Then** 调用 `RetrievalPipeline.retrieve()`(含 filter 白名单校验、rerank 失败回退)
**And** 返回结果格式化为 tool message,内容控制在 token 预算内(如只返回 Top-5 摘要)
**And** 全程写入 `query_logs.tool_trace`:调用次数、每次参数、命中数、max_score
**And** 与编排框架研究的 `AgentGraphRunner` 集成测试通过(固定 LLM 响应序列断言路由)

### Story 12.4: Agent 循环预算与终止条件

As a 系统，
I want Agent 的检索循环有明确的终止条件，
So that 不会出现无限多跳或延迟爆炸。

**Acceptance Criteria:**

**Given** `agent_max_hops`(默认 2)、`agent_max_total_tokens`(可配置)、`agent_max_latency_ms`(可配置)
**When** Agent 进入检索-评估-改写循环
**Then** 任一条件达到即终止循环,进入生成或拒答
**And** 终止原因记录到 `tool_trace.termination_reason`
**And** 终止后若已有检索结果则生成,若无足够结果则拒答
**And** 提供单元测试:固定 LLM 响应序列断言 hop 上限触发终止边

---

## Epic 13: 多模态检索 PoC

**Epic Goal:** 接入 DashScope 多模态嵌入,让系统能用文本 query 检索图片/截图/文档页面,验证跨模态召回效果。

### Story 13.1: 多模态嵌入 Stage 与 Milvus 存储扩展

As a 系统，
I want 对图片/截图生成向量并写入独立的多模态索引，
So that 文本 query 可以跨模态召回。

**Acceptance Criteria:**

**Given** 新增配置项 `multimodal_embedding_provider` / `multimodal_embedding_model` / `multimodal_embedding_dim`(默认走 DashScope multimodal-embedding)
**When** `MultimodalEmbeddingStage.execute(images: list[ImageInput])` 执行
**Then** 支持输入:本地文件路径、base64、URL(统一抽象为 `ModalityInput`)
**And** 调用 `ModelClient.embed_multimodal()`(OpenAI 兼容协议封装)
**And** 输出向量写入 `MilvusStore` 的并列 collection 族,schema 与文本 collection 同构但 collection_name 带 `_multimodal` 后缀
**And** 复用 `IndexMetadataStore` 版本化机制(kb_id + multimodal 标志)

### Story 13.2: 多模态检索路由与融合

As a 用户，
I want 问"这个报错截图是什么意思"时系统能召回相关截图，
So that 图片类知识源可用。

**Acceptance Criteria:**

**Given** 用户问题为纯文本,但意图涉及图像
**When** `RetrievalPipeline` 在 `mode=multimodal` 或 `mode=auto` 下执行
**Then** 对文本 query 生成多模态嵌入,从多模态 collection 召回 Top-K
**And** 返回结果包含图片路径/缩略图 URL 与原始来源元信息
**And** 在 `mode=auto` 时,LLM 小模型/规则判断是否需要走多模态路(Phase 1 可简化为根据 query 关键词如"截图"路由)
**And** 多模态结果与文本结果可独立返回,不在 RRF 中混排(避免分数口径不一致)

### Story 13.3: 多模态评测小集

As a 开发者，
I want 用 20-50 条样本验证跨模态召回效果，
So that 决定是否继续投入多模态。

**Acceptance Criteria:**

**Given** 准备含截图/图表/文档页的知识库子集
**When** 构建评测问题(如"截图中的错误代码代表什么")
**Then** 至少 20 条问题,每条标注期望召回的图片/页面 ID
**And** 运行脚本输出 recall@5 / recall@10
**And** 结果写入 `eval_results` 表或独立 JSON,支持与文本-only 管线对比
**And** 评测集作为 PoC 退出条件:recall@5 达到可演示阈值(如 ≥50%)或明确给出不继续的结论

---

## Epic 14: 晚交互文档智能研究项(ColPali 式)

**Epic Goal:** 评估 ColPali/ColQwen 式「文档页面截图直接嵌入、跳过 OCR/切分」的方案,作为未来企业文档智能的潜在路径。

### Story 14.1: ColPali 检索管线 PoC(离线)

As a 研究者，
I want 对扫描件/复杂版式 PDF 子集跑通 ColPali 式嵌入与检索，
So that 评估其召回质量与存储成本。

**Acceptance Criteria:**

**Given** 选取 50-100 页扫描件或复杂版式 PDF
**When** 使用 `colpali-engine` 或 DashScope/Qwen-VL 多模态嵌入生成每页向量(晚交互:token 级向量)
**Then** 建立独立离线索引,不与主流程耦合
**And** 对 20 条版式相关问题输出 recall@5 与答案正确率
**And** 记录每页向量数、存储占用、索引耗时
**And** 输出与现有「OCR+切分+文本嵌入」管线的对照报告

### Story 14.2: 成本与工程可行性评估

As a 架构师，
I want 明确 ColPali 式方案是否值得引入主流程，
So that 不做无依据的架构决策。

**Acceptance Criteria:**

**Given** PoC 数据(recall、存储、耗时)
**When** 召开/书写评估
**Then** 输出决策记录(ADR),包含:
  - 质量收益:版式复杂场景的 recall 提升幅度
  - 成本代价:存储膨胀倍数、索引重建耗时、在线检索延迟
  - 工程侵入度:是否需要替换 `ChunkingStage`、是否需要新 embedding 服务
  - 推荐结论:继续/暂缓/仅在扫描件场景启用
**And** ADR 存入 `docs/adr/` 或 `_bmad-output/planning-artifacts/architecture/`
**And** 若结论为继续,则拆分为新的 Epic;否则列为技术储备

---

## 跨 Epic 基础设施

### Story X.1: 评测集扩充(与 Epic 10-14 并行)

As a QA，
I want 评测集覆盖时效、多约束、多模态三类意图，
So that 新能力有度量标准。

**Acceptance Criteria:**

**Given** 现有 `eval/eval_set.json`
**When** 扩充至少:
  - 10 条时效意图问题(期望触发 updated_at 过滤或生成后时效提示)
  - 10 条多约束问题(含来源类型/时间范围,期望 self-querying 产出 filter)
  - 20 条多模态/版式问题(图片/截图/表格)
**Then** 每条标注 ground_truth、期望引用、是否应拒答、期望行为标签
**And** 评测脚本能按标签分组输出指标

### Story X.2: tool_trace 数据结构落地(支撑 Epic 12)

As a 开发者，
I want 一个 JSON 结构记录 Agent 的工具调用轨迹，
So that 可审计、可复盘、可面试展示。

**Acceptance Criteria:**

**Given** Agent/工具调用发生
**When** 记录轨迹
**Then** 字段包含:
  - `decisions`: 各节点路由决策(plan/grade/rewrite)
  - `tool_calls`: 工具名、参数、结果摘要、latency
  - `hop_count`: 实际跳数
  - `max_scores`: 每跳最大检索分数
  - `termination_reason`: 终止原因
**And** 写入 `query_logs.tool_trace` JSON 列
**And** 前端/admin 可在详情页展示(至少可读 JSON,admin 可格式化展示)

---

## Epic 优先级与依赖

| 优先级 | Epic | 前置依赖 | 大概工期 | 产出 |
|---|---|---|---|---|
| P0 | Epic 10 Filtering 产品化 | Phase 1 完成 | 1-2 天 | 检索期过滤、self-querying 白名单 |
| P1 | Epic 11 级联观测与索引对照 | Epic 10(可选并行) | 1-2 天 | query_logs 扩列、shadow 对照 |
| P2 | Epic 12 检索能力工具化 | Epic 10-11 + 编排研究 Phase 1-2 | 2-3 天 | Agent 可调用的 retrieval tool |
| P3 | Epic 13 多模态检索 PoC | Epic 12(可选) | 2-3 天 | 跨模态召回可演示 |
| P4 | Epic 14 晚交互研究项 | Epic 13 数据 | 3-5 天(研究型) | ADR 与质量/成本报告 |

**关键路径:** Epic 10 → Epic 11 → Epic 12 → Epic 13 → Epic 14。
**汇合点:** Epic 12 与同日编排框架研究的 Phase 3 必须合并实现,避免 tool schema 重复设计。

---

## 风险与验收总览

- **R1 权限过滤被下放到 Agent:** 验收 Epic 10 时必须确认安全过滤(租户/kb_id)仍由 API 层/图外代码决定,不在 tool schema 中暴露
- **R2 工具调用导致延迟爆炸:** 验收 Epic 12 时必须通过固定 LLM 响应序列的单测验证 `agent_max_hops` 终止
- **R3 多模态存储成本失控:** 验收 Epic 13/14 时必须输出每页/每张存储成本与 recall 数据,作为继续/停止依据
- **R4 评测集跟不上能力:** 验收每个 Epic 时必须同步交付对应标签的评测样本,否则不算完成

---

**Story 编写日期:** 2026-07-15  
**输入研究文档:** `technical-agentic-rag-key-technologies-research-2026-07-15.md`  
**关联编排研究:** `technical-agentic-rag-orchestration-frameworks-research-2026-07-15.md`
