---
title: "CloudBrief 支持副驾 — 架构设计说明（面试讲解版）"
created: 2026-07-02
updated: 2026-07-03
---

# CloudBrief 支持副驾 — 架构设计说明（面试讲解版）

> 本文档面向作品集读者与面试官，用自然语言解释架构 spine 中的关键决策、数据流与取舍。对应的 terse spine 见 `ARCHITECTURE-SPINE.md`。

## 1. 整体设计思想

我们采用 **"显式阶段管道"（Pipes-and-Filters）** 范式，把整个 RAG 链路拆成三个 Pipeline：

1. **IndexingPipeline**：原始文档 → 切分 → 生成 Embedding → 写入 Milvus + 重建 BM25 索引
2. **RetrievalPipeline**：用户问题 + 会话历史 → 查询改写 → 向量检索 + 关键词检索 → RRF 融合 → Reranker 精排
3. **GenerationPipeline**：Top-N 证据 + 问题 → LLM 生成答案 → 解析引用 → 拒答/时效判断

### 为什么拆成 Pipeline？

- **边界清晰**：每个阶段只干一件事，输入输出用 Pydantic DTO 固定。新同学看目录就知道数据怎么流。
- **可测试**：每个 Stage 可以单独跑单元测试，评测脚本也能只测检索、不跑生成。
- **可替换**：同一 Stage 接口下，可以塞 Native 实现，也可以塞 LangChain 适配器，方便做对比实验。

### 为什么 Pipeline 里还要保留 LangChain 适配器？

作品集的核心叙事是：**我不只会调包，我能自己实现 RAG 链路；但我也知道行业框架怎么用**。所以主路径是自研 Native Stage，LangChain 适配器作为同接口的可插拔实现。面试时可以讲：

> "我先定义了阶段契约，用 Native 实现保证对 RRF、引用、拒答的可控性；同时也提供了一个 LangChain 适配器，证明我能在成熟框架里快速落地。"

---

## 2. 关键技术选型与取舍

### 2.1 后端：FastAPI

选 FastAPI 而不是 Flask/Django：
- 现代 Python 异步 API 标准，性能足够作品集演示。
- 自动生成 OpenAPI / Swagger，面试 demo 时可以直接展示 API 文档。
- Pydantic 原生集成，和我们的 DTO 契约完美契合。

### 2.2 向量库：Milvus

PRD 附录里本来列了 Chroma / FAISS / Qdrant，但用户明确要求 **Milvus**。

- **优点**：生产级向量数据库，支持分布式、多副本、复杂索引类型。面试时讲"为什么上 Milvus"能体现真实工程经验。
- **代价**：本地演示需要 Docker Compose 拉起 Milvus（Standalone 模式即可），比 Chroma 重。
- **折中**：Milvus Standalone 模式对作品集完全够用，不需要上 K8s 集群。

### 2.3 Embedding：text-embedding-v3

阿里云 DashScope 的 embedding 模型。
- 默认 1024 维，支持 Matryoshka 降维（64–1024）。
- 中文效果好，通过统一 `ModelClient` 调用，密钥和重试逻辑集中管理。

### 2.4 Reranker：qwen3-rerank

Qwen3 系列的重排模型，我们默认用 **0.6B** 版本。
- 1.2GB 左右，本地 GPU 或 CPU 可跑。
- 通过 DashScope API 调用也可以，降低本地部署压力。
- Reranker 是 RAG 链路里的"精筛"环节，直接决定进入生成阶段的证据质量。

### 2.5 生成 LLM：qwen3.7-plus + 本地开源 fallback

主模型用阿里云 **qwen3.7-plus**，OpenAI 兼容接口，100 万 token 上下文。
- 国产模型生态，面试时展示对国内大模型平台的熟悉度。
- 同时通过 `ModelClient` 抽象预留了 **本地开源 LLM** 切换能力（vLLM / Ollama + Qwen3 开源版），体现"不依赖单一供应商"的设计。

### 2.6 异步任务：Celery + Redis

索引重建是重任务（读文件、切分、调 embedding、写 Milvus、重建 BM25），不能阻塞 HTTP 请求。
- **Celery + Redis** 比 FastAPI BackgroundTasks 更"生产形态"：任务可持久化、可监控、Worker 可独立扩缩。
- 代价：本地需要 Redis。用 Docker Compose 一起拉起。

### 2.7 会话持久化：MySQL

多轮对话需要保存历史消息。MySQL 比 SQLite 更像生产环境，也为未来多实例部署预留了共享状态能力。

---

## 3. 核心数据流

### 3.1 用户提问

```
用户输入
  → Next.js 前端
  → POST /chat (conversation_id?)
  → ChatService
    → 读取/创建 MySQL 会话
    → RetrievalPipeline
      → QueryRewritingStage（把"那 Excel 呢？"改写成完整查询）
      → EmbeddingStage（Milvus 向量检索）
      → BM25Stage（关键词检索）
      → HybridFusionStage（RRF 融合，k=60）
      → RerankingStage（qwen3-rerank）
    → GenerationPipeline
      → 判断证据是否足够？不足 → 拒答
      → 足够 → qwen3.7-plus 生成答案
      → 解析引用、检查时效
    → 保存消息到 MySQL
  → 返回前端展示（答案 + 可点击引用 + 时效提示）
```

### 3.2 重建索引

```
前端点击"重建索引" / 管理后台触发
  → POST /index/rebuild
  → 发布 Celery 任务
  → 前端拿到 task_id，同时建立 SSE 连接 /index/tasks/{id}/events
  → Celery Worker
    → ParsingStage 解析 data/ 下知识源（Native 或 LlamaIndex 双路径）
    → ChunkingStage 切分
    → EmbeddingStage 生成向量
    → 写入 Milvus 新 collection
    → 重建 BM25 索引
    → 原子切换 MySQL index_metadata 表中的 active 记录
  → 每步状态通过 SSE 实时推送到前端（步骤名、状态、耗时、日志）
  → 查询服务继续用旧索引，切换完成后用新索引
```

### 3.3 RAGAS 评测审计

```
评测脚本 / 管理后台触发评测
  → 对评测集每个问题调用完整 RAG 链路
  → 用 RAGAS 计算 context_relevance / context_precision / context_recall / faithfulness / answer_relevance
  → 将 retrieved contexts、scores、reasoning 写入 MySQL eval_results 表
  → 管理后台审计页展示：问题 / 期望答案 / 生成答案 / 检索片段 / 指标分数 / reasoning
  → 支持人工评分、备注、是否采用/修改
```

---

## 4. 防止幻觉的三道防线

这是本系统最值钱的设计，面试重点：

1. **检索隔离**：LLM 只能看到检索到的 Top-N 片段，不能直接访问向量库或原始文档。
2. **硬分支拒答**：Reranker 分数不够时，直接返回"知识库中没有相关信息"，不进 LLM。
3. **强制引用**：每个答案必须带 `citations`，没有 citation 的答案不能返回给用户。

---

## 5. 扩展性设计

虽然 MVP 聚焦核心 RAG，但架构为以下方向预留了空间：

- **增量索引更新**：后续只需要增加变更检测 Stage，替换全量重建的入口。
- **多实例部署**：状态已经外置（Milvus/MySQL/Redis），FastAPI 本身无状态，水平扩展只需多开实例。
- **多模型切换**：`ModelClient` 抽象让 embedding/rerank/LLM 都可以换成其他供应商。
- **解析双路径**：同一 `Document` DTO 下可切换 Native 与 LlamaIndex 解析器，便于面试对比与演进。
- **评测审计扩展**：`eval_results` 表保存 RAGAS 过程数据与人工反馈，支持后续 A/B 对比与模型迭代。

---

## 6. 本地开发环境

用 Docker Compose 一键拉起所有依赖：

- Milvus Standalone
- Redis
- MySQL

后端和前端在本地分别启动。评测脚本独立运行，不依赖 Web 服务。

---

## 7. 面试时可以这样讲

> "CloudBrief 支持副驾的架构分三层：前端是 Next.js + LlamaIndex UI；后端是 FastAPI；数据层用 Milvus 做向量检索、BM25 文件做关键词、MySQL 存会话、Redis 给 Celery 做任务队列。
>
> 核心链路是显式 Pipeline：IndexingPipeline 把知识库切成片段建索引；RetrievalPipeline 做混合检索 + RRF + qwen3-rerank 精排；GenerationPipeline 基于证据生成带引用的答案，证据不足直接拒答。
>
> 我特意做了两个设计来展示工程深度：第一，每个 Stage 都有统一接口，主路径是自研 Native 实现，同时提供了 LangChain 适配器做对比；第二，所有外部模型调用都走 ModelClient 抽象，主模型是 qwen3.7-plus，但可以一键切换到本地 vLLM/Ollama，避免被单一供应商绑定。"

