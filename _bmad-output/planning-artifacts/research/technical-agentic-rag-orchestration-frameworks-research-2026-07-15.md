---
stepsCompleted: [1, 2, 3, 4, 5, 6]
inputDocuments: []
workflowType: 'research'
lastStep: 1
research_type: 'technical'
research_topic: 'Agentic RAG 编排框架选型：LangGraph StateGraph vs LlamaIndex Workflows vs 自研 DAG（面向 CloudBrief 支持副驾）'
research_goals: '为 CloudBrief 支持副驾引入 Agentic RAG（自主检索策略、Tool Use、多跳推理）选择编排方案，产出带证据的对比结论与分阶段落地路径'
user_name: 'Yechen'
date: '2026-07-15'
web_research_enabled: true
source_verification: true
---

# Research Report: technical

**Date:** 2026-07-15
**Author:** Yechen
**Research Type:** technical

---

## Research Overview

本调研为 CloudBrief 支持副驾（FastAPI + Next.js 企业 RAG 系统）的 Agentic RAG 编排选型提供决策依据，对比三个候选：LangGraph StateGraph、LlamaIndex Workflows、自研 DAG（项目现状）。调研方法为六步流程：范围确认 → 技术栈核验 → 集成模式分析 → 架构模式分析 → 实施研究 → 综合成稿；全部关键事实经 PyPI 官方元数据、GitHub API、arXiv 原文、阿里云与框架官方文档核验，并逐条标注置信度。

核心结论：**采用 LangGraph StateGraph，以"图内确定性路由 + 节点内受限自主"的架构分 5 个阶段（Phase 0-4，约 5-8 天）渐进引入 Agentic RAG。** 项目自身的五个接缝（Stage 统一契约、`retrieval_adapter` 切换机制、结构化 SSE 协议、GraphRAG shadow 灰度先例、RAGAS 评测链路）使本次引入为"平移 + 扩展"而非重写；拒答阈值、权限校验、跳数终止等护栏保留在代码控制的条件边，双路径并行 + 后台开关使回滚成本接近零。

完整的发现、论证、路线图与风险登记见下方 **Research Synthesis** 章节的执行摘要；技术栈、集成、架构、实施四个域的详细分析与逐条来源引用见对应正文章节。

---

<!-- Content will be appended sequentially through research workflow steps -->

## Technical Research Scope Confirmation

**Research Topic:** Agentic RAG 编排框架选型：LangGraph StateGraph vs LlamaIndex Workflows vs 自研 DAG（面向 CloudBrief 支持副驾）
**Research Goals:** 为 CloudBrief 支持副驾引入 Agentic RAG（自主检索策略、Tool Use、多跳推理）选择编排方案，产出带证据的对比结论与分阶段落地路径

**Technical Research Scope:**

- Architecture Analysis - design patterns, frameworks, system architecture
- Implementation Approaches - development methodologies, coding patterns
- Technology Stack - languages, frameworks, tools, platforms
- Integration Patterns - APIs, protocols, interoperability
- Performance Considerations - scalability, optimization, patterns

**Research Methodology:**

- Current web data with rigorous source verification
- Multi-source validation for critical technical claims
- Confidence level framework for uncertain information
- Comprehensive technical coverage with architecture-specific insights

**Scope Confirmed:** 2026-07-15

## Technology Stack Analysis

### 编程语言

Python 是两个候选框架的共同门槛，且与本项目完全兼容。

_主流语言:_ Python。`langgraph` 要求 `requires_python>=3.10`，`llama-index-workflows` 同样 `>=3.10`；本项目 backend `requires-python = ">=3.11"`，无任何版本摩擦。
_TypeScript 侧:_ LangGraph 与 LlamaIndex 均有 JS/TS 版本，但编排逻辑应全部留在 Python 后端（本项目检索/生成全部在后端），前端只消费 SSE，TS 版本与本选型无关。
_置信度:_ 高（PyPI 官方 `requires_python` 字段）。
_Source: https://pypi.org/pypi/langgraph/json ; https://pypi.org/pypi/llama-index-workflows/json_

### 核心框架与库（编排层）

三个候选：LangGraph StateGraph、LlamaIndex Workflows、自研 DAG（项目现状）。

_LangGraph:_ **1.2.9**（2026-07-10 发布，PyPI 核验）。2025-10 发布 1.0 并给出长期 API 稳定承诺（changelog 记录 v1.1 stable 于 2025-10-22）。定位为"低层、持久的 agent 编排运行时"：StateGraph + 条件边 + checkpointer + 人机中断均为一等公民。LangChain 1.x 的 `create_agent` 即构建于 LangGraph 之上。
_LangChain:_ **1.3.13**（2026-07-10，PyPI 核验）。与 LangGraph 分工明确：LangChain 提供 agent 抽象，LangGraph 提供编排原语。本项目现有 `langchain>=0.2.0` 约束可平滑升级至 1.x（需验证现有 `LangChainRetrievalStage` 适配器在 1.x 下的行为，见 Step 5 风险）。
_LlamaIndex Workflows:_ 独立包 **llama-index-workflows 2.22.2**（2026-06-30，PyPI 核验）。事件驱动模型（`@step` + 自定义 Event），Workflows 2.x 为当前主线，1.x 已弃用。注意 llama-index 核心包仍为 **0.14.23**（0.x 版本线，无 1.0 API 稳定承诺）。
_关键区分:_ 被标记 deprecated 的是 `llama-agents`（多 agent 部署实验包，ALPHA 且已弃用），**不是** llama-index-workflows 本身——Workflows 2.x 活跃维护中。选型时勿被"LlamaIndex agents 已弃用"的二手信息误导。
_自研 DAG:_ 即项目现状（`ChatService.ask_stream` 线性编排）。零新依赖、完全可控，但循环重试、分支路由、状态持久化、中断恢复全部要手写，且不可可视化。
_置信度:_ 高（版本与日期来自 PyPI）；中高（llama-agents 弃用状态来自 deepwiki 二手源，但不影响主结论）。
_Source: https://pypi.org/project/langgraph/ ; https://pypi.org/project/langchain/ ; https://pypi.org/project/llama-index-workflows/ ; https://pypi.org/project/llama-index/ ; https://changelog.langchain.com ; https://docs.llamaindex.ai/en/stable/module_guides/workflow/_

### 状态持久化与存储（checkpointer 生态）

编排状态的持久化能力是三方案差异最大的维度，直接决定"多跳会话状态、中断恢复、人机协同"的实现成本。

_LangGraph checkpointer 生态（PyPI 核验）:_

- `langgraph-checkpoint` **4.1.1**（2026-05-22）— BaseCheckpointSaver 基座
- `langgraph-checkpoint-sqlite` **3.1.0** 与 `langgraph-checkpoint-postgres` **3.1.0**（2026-05-12）— 生产主流选项
- `langgraph-checkpoint-redis` **0.5.1**（2026-07-14，调研前一天刚发布）— 可直接复用本项目现有 Redis（6381 端口），但 0.x 版本线，成熟度待观察，建议作为 Phase 4 可选增强而非首日依赖

_LlamaIndex Workflows 侧:_ 提供 `Context` 对象可序列化，但未见官方 Redis/Postgres saver 生态，持久化需自行封装（置信度：中，基于官方文档未见对应组件）。
_与项目现有存储的关系:_ Milvus（向量）、Redis（锁/Pub-Sub）、MySQL（会话/配置）、Neo4j（图谱）的职责不受编排选型影响；checkpointer 是新增的"编排状态"存储，建议初期用 SQLite（零运维），验证价值后再迁 Redis。
_置信度:_ 高（PyPI）；中（LlamaIndex 持久化能力为"未见"型结论）。
_Source: https://pypi.org/project/langgraph-checkpoint/ ; https://pypi.org/project/langgraph-checkpoint-redis/ ; https://docs.llamaindex.ai/en/stable/module_guides/workflow/_

### 开发工具与平台（观测与调试）

_LangGraph 侧:_ LangSmith **0.10.4**（2026-07-14，PyPI 核验）提供原生 trace——每条边、每次工具调用、每个状态快照均可回放，与项目现有 `query_logs` 互补而非替代；LangGraph Studio 提供图形化调试与图导出（可作架构文档素材）。
_LlamaIndex 侧:_ 生态观测工具为 LlamaTrace / Arize Phoenix，与 LangSmith 同级。
_与项目现有观测的关系:_ 项目已有 prometheus-client 指标（检索/生成延迟、拒答率）。任何编排方案都应继续落现有指标管道，框架 trace 作为开发期调试工具，生产指标仍以自有埋点为准。
_测试:_ 两方案均为纯 Python 对象，pytest 友好；节点级单测可复用项目现有 Stage 测试基座。
_置信度:_ 高（PyPI + 官方文档）。
_Source: https://pypi.org/project/langsmith/ ; https://docs.smith.langchain.com_

### 部署与运行形态

_库内嵌形态（推荐）:_ LangGraph 与 LlamaIndex Workflows 都是 pip 库，可直接嵌入现有 FastAPI 进程，无需新增服务——与项目单机 docker compose 形态匹配。
_LangGraph Platform:_ 提供托管/自部署的 agent server（含任务队列、定时任务、Studio 联调）。对企业是选项，对本项目（作品集 + 单机 compose）属过度工程，不推荐。
_LlamaIndex 部署形态:_ 曾推 `llama_deploy`（llama-agents）作为部署方案，但该包为 ALPHA 且已弃用——LlamaIndex 侧目前事实上只剩"嵌进自己的服务"一种形态。
_与 Celery 的关系:_ 编排发生在请求路径（同步/流式响应），Celery 继续负责索引构建队列，两者无冲突。
_置信度:_ 高（部署形态来自官方文档）；中高（llama_deploy 弃用状态）。
_Source: https://docs.langchain.com/langgraph-platform/ ; https://docs.llamaindex.ai_

### 技术采用趋势

_Agentic RAG 主线:_ 2025-2026 年明确趋势是从"固定管线"向"图编排 + 受控自主"迁移；LangGraph 官方教程即用 Corrective RAG（检索质量评估 → 改写重试）作为标准示例（置信度：中高，官方教程存在，命名细节未逐字核验）。
_API 冻结拐点:_ LangChain/LangGraph 1.0（2025-10）标志 API 进入稳定期，企业/个人项目采用的版本风险显著下降；LlamaIndex 核心包仍在 0.x 版本线，API 变动风险相对更高。
_选型分化:_ 社区共识层面（置信度：中，来自对比文章与官方定位文档），LangGraph 在"需要显式控制流 + 持久化 + 人机协同"的场景占优；LlamaIndex Workflows 在"以检索为中心、轻量事件流"的场景更轻。本项目已有混合检索 + Rerank + GraphRAG 的多源上下文，且需要保留拒答硬分支等确定性护栏，属于前者场景。
_Source: https://changelog.langchain.com ; https://docs.langchain.com ; https://docs.llamaindex.ai/en/stable/module_guides/workflow/_

## Integration Patterns Analysis

本节不按通用 REST/GraphQL 模板展开，而是聚焦编排框架与 CloudBrief 现有六个真实接缝的集成协议（本地代码 + 官方文档双重核验）。

### 编排切换机制（系统互操作）

_现有模式:_ `config.py:77` 定义 `retrieval_adapter: Literal["native", "langchain"]`；`settings_service.py` 通过 `SettingMeta` 注册表（L59）实现运行期读写、DB 优先 / .env 回退（L183、L292）。`RetrievalPipeline.retrieve()` 在入口按该值分支。
_扩展方案:_ 新增 `orchestration_mode: Literal["native", "langchain", "agentic"]` 设置项，照搬 `SettingMeta` 注册模式即可获得后台切换开关与 `query_logs.config_snapshot` 快照记录；`ChatService.__init__` 按模式组装 `RetrievalPipeline`/`GenerationPipeline` 或新的 `AgentGraphRunner`。
_互操作结论:_ 三条路径共享同一份 Stage 契约（`AbstractStage[InputT, OutputT]`），不存在协议转换层；切换是编排层替换，不是检索层替换。
_置信度:_ 高（本地代码直读）。
_Source: backend/app/config.py ; backend/app/services/settings_service.py ; backend/app/pipelines/retrieval.py_

### 流式通信协议（SSE 事件映射）

_项目现状:_ `sse-starlette` 的 `EventSourceResponse`，事件协议为六种 `StreamEvent`（chunk / citations / status / done / error / sources），前端 `useTaskStream` 与 Chat 组件消费。
_LangGraph 侧（官方文档核验）:_ `graph.astream(..., stream_mode=[...])` 产出 `(namespace, mode, chunk)` 三元组；`stream_mode` 支持 `"values" | "updates" | "messages" | "custom" | "debug"`。映射关系：

- `"messages"`（LLM token 流）→ 现有 `chunk` 事件
- `"updates"`（节点完成、状态增量）→ 现有 `status` 事件（"正在检索…/正在改写重试…"）
- `"custom"`（节点内 `get_stream_writer()` 主动推送）→ 现有 `sources` 事件（检索完成后立即推来源列表，与当前 `ask_stream` 行为一致）
- 图执行结束 → `citations` + `done`

_结论:_ 前端协议零改动，只需在服务层做一次模式映射；这是 LangGraph 相对 LlamaIndex Workflows 的集成优势——后者需从 `handler.stream_events()` 事件流自行拼装等价协议（置信度：中高，官方文档未见现成的 token 级流模式）。
_置信度:_ 高（LangGraph 官方 how-to 与 API reference）。
_Source: https://langchain-ai.github.io/langgraph/how-tos/streaming/ ; https://reference.langchain.com/python/langgraph/types/ ; backend/app/services/chat_service.py_

### 工具调用协议（Tool Use）

_项目现状:_ `ModelClient.chat()`（model_client.py:180）是裸 httpx OpenAI 兼容客户端，payload 手拼（model/messages/stream/temperature/max_tokens），**无 tools 参数**；带 primary/secondary provider failover、超时与调用日志。
_模型侧能力（官方文档核验）:_ DashScope 兼容模式端点 `compatible-mode/v1/chat/completions` 支持 OpenAI 风格 `tools` / `tool_calls` function calling，官方示例直接用 OpenAI SDK 调用——与项目现有 `model_base_url` 完全同源。
_两条接入路线:_

- **路线 A（推荐）:** 扩展 `ModelClient.chat(tools=..., tool_choice=...)`，保住现有 failover/重试/日志，自行解析 `tool_calls` 响应。改动集中在单一客户端。
- **路线 B:** 用 `langchain-openai`（PyPI 核验 1.3.5，2026-07-10）的 `ChatOpenAI(base_url=..., api_key=...).bind_tools()` + `ToolNode`。生态原生、代码最少，但绕开 ModelClient 的 provider failover 与统一日志。

_分期结论:_ Phase 1-2（图内确定性路由）不需要 tool calling——LLM 只做分类/评估的结构化输出；Phase 3（检索工具化）才引入，届时选路线 A。
_置信度:_ 高（DashScope 官方文档 + 本地代码）。
_Source: https://help.aliyun.com/zh/model-studio/qwen-function-calling ; https://pypi.org/project/langchain-openai/ ; https://docs.langchain.com/oss/python/langchain/tools ; backend/app/clients/model_client.py_

### 状态持久化协议（会话 ↔ checkpoint）

_职责切分:_ 会话消息继续存 MySQL（`ConversationStore`），checkpointer 只存编排状态（`sub_questions`、`hop_count`、`tool_trace`、中间检索结果）。两者通过 `thread_id == conversation_id` 关联，避免双写真相源。
_落地序列:_ Phase 1-3 无 checkpointer（每次请求一张新图，无状态）；Phase 4 引入 `langgraph-checkpoint-sqlite`（零运维）验证价值，需要分布式时再迁 `langgraph-checkpoint-redis`（复用现有 Redis 6381）。
_置信度:_ 高（PyPI 版本已核验，见 Technology Stack 一节）。
_Source: https://pypi.org/project/langgraph-checkpoint-sqlite/ ; https://pypi.org/project/langgraph-checkpoint-redis/ ; backend/app/stores/conversation.py_

### 观测与日志协议

_query_logs 扩展:_ 现有字段（latency 分段、is_fallback、config_snapshot）新增 `tool_trace` JSON 列——记录路由决策、工具调用序列、跳数、各跳 max_score。这是 Agentic 路径的核心可观测资产。
_框架 trace:_ LangSmith 作为开发期调试（节点级回放），不进入生产关键路径；prometheus 指标（`RETRIEVAL_LATENCY` 等）增加 `orchestration_mode` 标签，保持现有埋点为准。
_评测协议:_ RAGAS eval 集同一数据集跑 native vs agentic 双路径，对比 faithfulness / answer relevancy 与拒答准确率；拒答口径（threshold 硬分支）留在图的条件边，保证两路径可比。
_置信度:_ 高（本地代码 + 既有评测链路）。
_Source: backend/app/services/chat_service.py (_log_query) ; backend/app/metrics.py ; backend/eval/run_eval.py_

### 认证与权限集成

_不变量:_ JWT 三通道（Bearer / Cookie / query token）在 API 层完成解析，图的输入状态只携带已鉴权的 `user_id` 与 `kb_id`。
_关键约束:_ `_resolve_kb_id` + `KbAccessStore` 权限校验必须在图入口**之前**完成——权限是确定性前置门槛，不能下沉为 Agent 可决策的节点，否则 Agent 的路由自由度会变成越权面。
_GraphRAG 访问:_ 沿用 `GraphSchemaStore` 的 per-kb 开关（enabled / shadow_mode），图节点读取同一开关决定是否提供 graph 工具。
_置信度:_ 高（本地代码）。
_Source: backend/app/services/chat_service.py (_resolve_kb_id) ; backend/app/stores/kb_access.py_

### 后台任务与灰度边界

_Celery 边界:_ 索引构建队列（kb.index.rebuild / kb.index.single / kb.graph.rebuild）与请求路径编排完全正交，不受影响。
_灰度机制复用:_ GraphRAG shadow mode（`graph_shadow_store` + `graphrag_enabled/graphrag_used` 日志字段）已验证"旁路对照"模式可行——Agentic 路径上线时用同一模式先跑 shadow 对照，再切主路径，风险与 GraphRAG 上线同级。
_置信度:_ 高（本地代码存在该先例）。
_Source: backend/app/services/chat_service.py (_record_shadow_async) ; backend/app/stores/graph_shadow_store.py_

## Architectural Patterns and Design

### 编排架构模式（三候选的形态对比）

_显式状态图（LangGraph StateGraph）:_ 节点是纯函数（State in → partial State out），边是显式控制流，状态是 TypedDict + reducer 合并。循环、分支、中断是一等公民；图可编译为模块级单例复用，可导出 mermaid 图直接当架构文档。确定性护栏落在条件边上，代码可审计。
_事件驱动工作流（LlamaIndex Workflows 2.x）:_ `@step` 方法 + 自定义事件路由，控制流隐含在事件类型匹配中。同等表达能力，但循环是"事件回发"而非显式回边——流程的可读性与可审计性弱于显式图，尤其当步骤数 > 6 时（置信度：中，基于两框架文档的结构对比）。
_手写编排（自研，项目现状）:_ 控制流 = 代码路径，无独立状态模型。零依赖、完全可控，但每加一个分支（重试、多跳、工具选择）都是一次 `ask_stream` 的侵入式修改，SSE 事件与业务逻辑耦合在单一函数中。
_结论:_ 本项目的演进方向（多跳 + 工具化 + 灰度对照）会持续增加分支与循环，显式状态图的边际收益最高。
_Source: https://docs.langchain.com/oss/python/langgraph/overview ; https://docs.llamaindex.ai/en/stable/module_guides/workflow/ ; backend/app/services/chat_service.py_

### Agentic RAG 规范架构模式（学术 + 工业核验）

_Corrective RAG（CRAG）:_ arXiv 2401.15884《Corrective Retrieval Augmented Generation》（2024-01-29，已核验）。核心结构：检索评估器 → correct / ambiguous / incorrect 三分支 → 知识精炼 / 查询改写 / 兜底。**映射到本项目：grade 节点 + 改写重试边**，用 LLM 轻量评估替代论文中的训练版评估器（工程版 CRAG，与训练版区分）。这是 Phase 2 的直接蓝本，也是 LangGraph 官方教程的标准示例（置信度：中高）。
_Self-RAG:_ arXiv 2310.11511《Self-RAG: Learning to Retrieve, Generate, and Critique through Self-Reflection》（2023-10-17，已核验）。将 reflection tokens 训练进模型以自评检索质量。对本项目是 overkill（需要微调），但其"按需检索"思想直接对应 plan 节点的路由判定——思想借用，实现不借用。
_Adaptive RAG:_ 按查询复杂度路由到 无检索 / 单步 / 多步 三档（置信度：中，arXiv 2403.14403 未逐字核验）。映射为 plan 节点的三档路由输出，与 CRAG 的 grade 节点组合成"前置路由 + 后置纠偏"的双闸门结构。
_自主性光谱（架构选型核心张力）:_

- **ReAct 全自主循环：** LLM 决定一切（何时检索、检索什么、何时停）。token 成本高、行为不可审计、拒答口径失控——企业场景与作品集叙事都不推荐作为主结构。
- **Plan-Execute 两阶段：** 先规划后执行，适合长任务，对单轮问答偏重。
- **图内确定性路由 + 节点内受限自主（推荐）：** 边（拒答、跳数、终止）由代码控制；节点内（分类、分解、评估、工具参数）由 LLM 决策。自由度被架构显性约束，这正是"受控自主"的工程化表达。

_Source: https://arxiv.org/abs/2401.15884 ; https://arxiv.org/abs/2310.11511 ; https://docs.langchain.com_

### 确定性护栏的架构位置（设计原则）

_护栏即边，不是提示词:_ 拒答阈值（`refusal_threshold`）、时效检查、引用解析、权限校验全部落在条件边或前置/后置节点——它们的正确性不依赖 LLM 行为，agentic 化前后口径完全一致。这是本项目相对"LLM 自由发挥式 agent"的架构差异点，也是双路径（native / agentic）可对比评测的前提。
_终止条件显性化:_ `max_hops`（建议 2-3）+ 每跳 token 预算 + 总延迟预算写入图配置并暴露为运行期设置（沿用 `SettingMeta` 模式），防止评估-重试边形成无限循环。
_置信度:_ 高（本地代码现有护栏）/ 中高（行业实践一致性）。
_Source: backend/app/pipelines/generation.py ; backend/app/services/settings_service.py_

### 性能与可扩展架构

_延迟预算:_ 每个 agentic 节点（plan / grade）= +1 次 LLM 调用，经验量级 +0.5-2s/次（置信度：中，取决于模型与输出长度）。设计对策：评估节点用短输出（结构化 JSON 判定），`max_hops=2` 封顶，首字延迟靠 generate 节点的 token 流保住（CRAG 重试发生在生成之前，不影响 TTFB）。
_并发模型:_ 同步 Stage 继续用 `asyncio.to_thread` 包裹（`ask_stream` 现有模式），图节点全部 async；多跳的 `sub_questions` 可并行检索（LangGraph Send API 或节点内 `asyncio.gather`，置信度：中）。
_成本观测:_ `tool_trace` 记录每次 LLM 调用的模型/延迟/token 用量，落 `query_logs`——成本可见是 agentic 功能上线的前置条件。
_Source: backend/app/services/chat_service.py ; https://docs.langchain.com_

### 安全架构

_越权面:_ 已在 Step 3 定调——鉴权与 kb 权限前置，不进入图的决策空间。
_注入面:_ 检索内容进入 LLM 上下文是固有 prompt 注入面；agentic 化后改写/分解/评估节点都接触检索内容，注入面变宽但性质不变。护栏：工具输出结构化（schema 约束）、系统提示固定不拼接检索原文、评估节点只输出判定不生成用户可见文本。
_置信度:_ 中（通用实践，未见针对本项目形态的公开威胁模型）。
_Source: backend/app/pipelines/generation.py_

### 数据架构

_状态 schema 复用:_ 图 State 中的检索结果直接复用 `RetrievalResult` Pydantic 契约，无 DTO 转换层；`tool_trace` 为新增 JSON 结构（路由决策、工具调用序列、跳数、各跳 max_score）。
_存储职责:_ 会话消息 → MySQL（现状）；编排状态 → 初期无持久化，Phase 4 起 checkpointer（SQLite→Redis）；观测数据 → `query_logs` 扩列。
_Source: backend/app/stages/base.py ; backend/app/services/chat_service.py_

### 部署与运维架构

_形态:_ 库内嵌 FastAPI 单进程，图编译为模块级单例（构建一次，请求间复用）。docker compose 服务清单不变；Celery 队列不变；LangGraph Platform 不引入（Step 2 已论证）。
_灰度:_ 复用 GraphRAG shadow 模式旁路对照 → 后台开关切流 → `query_logs` 对比，三级推进。
_Source: backend/app/services/chat_service.py ; https://docs.langchain.com/langgraph-platform/_

## Implementation Approaches and Technology Adoption

### 技术采用策略（渐进迁移）

_Strangler Fig 模式:_ 新 agentic 路径与现有 native/langchain 路径并行存在，通过后台 `orchestration_mode` 开关切流，native 路径永久保留为回退。这是项目 adapter 先例（`retrieval_adapter`）的自然延伸，不做 big bang 替换。
_阶段门采用:_ Phase 0-4 每阶段独立可交付、独立可演示；每阶段以 shadow 对照先行、RAGAS 回归守门，未过门不进入下一阶段。
_置信度:_ 高（与项目既有 GraphRAG 上线模式同构）。
_Source: backend/app/services/settings_service.py ; backend/app/services/chat_service.py_

### 开发工作流与工具

_依赖管理:_ `uv add langgraph langgraph-checkpoint`；`uv run ruff check .` 与现有检查链不变。注意 langgraph 1.2.x 会带动 langchain-core 升级——现有 `langchain>=0.2.0` 约束兼容 1.x，但需跑通 `LangChainRetrievalStage` 适配器验证行为（见风险 R4）。
_图即代码:_ StateGraph 定义集中在 `app/orchestration/`（新目录），编译单例；`graph.get_graph().draw_mermaid()` 导出图直接进架构文档（置信度：中高，API 存在）。
_Prompt 资产化:_ plan / grade 节点的提示词与 `QueryRewriteStage` 同模式管理（独立 stage 文件 + 模板常量），可随 `query_logs` 采样复盘迭代。
_Source: backend/pyproject.toml ; backend/app/stages/query_rewrite.py ; https://docs.langchain.com_

### 测试与质量保障

_现有基座:_ `backend/tests/` 下 9 个 pytest 文件（store/service 级），`pytest-asyncio` 已就位。
_三层测试设计:_

- **Stage 单测** — 现有测试不动，Stage 契约不变是本次改造的不变量
- **节点单测** — LLM 调用 stub 化（monkeypatch ModelClient），断言每个图节点的状态增量
- **图级测试** — 固定 LLM 响应序列，断言条件边路由（低分→重试边、空检索→拒答边、hop 上限→终止边）；checkpointer 用 InMemorySaver 注入（置信度：中高）

_评测守门:_ RAGAS eval 集同一数据集双路径跑分（faithfulness / answer relevancy / 拒答准确率）；eval 集补充多跳问题样本，否则 agentic 价值无法被度量。
_Source: backend/tests/ ; backend/eval/run_eval.py ; https://docs.langchain.com_

### 部署与运维实践

_部署形态:_ 无新服务、无 compose 变更；图编译单例无共享可变状态，uvicorn 多 worker 安全（置信度：中高）。
_灰度与回滚:_ shadow 对照 → 全库开关切流；回滚 = 后台切回 native，秒级生效，无数据迁移。
_运维关注:_ `tool_trace` 落 `query_logs` 后，每周采样复盘路由决策质量；prometheus 指标加 `orchestration_mode` 标签后即可在现有 dashboard 对比双路径延迟分布。
_Source: backend/app/services/settings_service.py ; backend/app/metrics.py_

### 团队组织与技能

_技能需求（单人作品集规模）:_ LangGraph 核心概念四件套——StateGraph / reducer / 条件边 / stream_mode，官方 quickstart 量级约 1-2 天上手（置信度：中）。不需要掌握 LangGraph Platform、多 agent 协作、subgraph 嵌套等高级主题，Phase 1-3 用不到。
_知识资产:_ mermaid 导出图 + `tool_trace` 样本 + 本调研文档，构成面试可展示的完整叙事链。
_Source: https://docs.langchain.com_

### 成本优化与资源管理

_节点成本:_ plan / grade 节点低 temperature + 短 `max_tokens` + JSON 结构化输出；可降级到更便宜模型（如 qwen flash 档，置信度：中，模型名以后台配置为准）。
_检索成本:_ 第二跳起 `top_k` 减半收敛；`max_hops=2` 封顶。
_成本可见:_ 每次 LLM 调用的模型/延迟/token 入 `tool_trace`，成本审视依赖数据而非体感。
_Source: backend/app/clients/model_client.py_

### 风险评估与缓解

- **R1 LLM 路由误判**（中概率/中影响）→ `query_logs` 采样复盘 + prompt 迭代；拒答硬分支兜底，误判不会击穿拒答口径
- **R2 延迟膨胀**（中/中）→ `max_hops=2`、评估节点短输出、预算配置化；TTFB 由 generate 节点 token 流保住
- **R3 token 成本上升**（高/低）→ 节点精简 + 成本入 `tool_trace`，月度审视
- **R4 langchain 0.2→1.x 升级破坏现有 LC 适配器**（中/中）→ 升级后首先跑 `LangChainRetrievalStage` 路径验证；必要时锁定 langchain 版本区间
- **R5 双路径行为漂移**（低/中）→ 同一 eval 集双跑 + shadow 对照；拒答口径共享同一边逻辑
- **R6 langgraph-checkpoint-redis 0.x 成熟度**（低/低）→ Phase 4 才引入，先 SQLite 验证

## Technical Research Recommendations

### Implementation Roadmap

- **Phase 0（0.5 天）:** `uv add langgraph langgraph-checkpoint`；新增 `orchestration_mode` 设置项（SettingMeta 注册 + 后台可见）；退出条件：开关可切换且无行为变化
- **Phase 1（1-2 天）:** 线性平移——`ask_stream` 流程建成等价 StateGraph（rewrite→retrieve→generate），SSE 三模式映射；退出条件：现有测试全绿 + RAGAS 基线与 native 持平
- **Phase 2（1-2 天）:** CRAG 化——加 `grade` 节点 + 改写重试边（`max_hops=2`）；退出条件：低质检索用例的回答率/拒答准确率改善可量化
- **Phase 3（2-3 天）:** 工具化 + 多跳——`plan` 节点三档路由（直检/多跳/图谱），`ModelClient.chat` 扩 tools 参数（路线 A），`tool_trace` 落 `query_logs`；退出条件：多跳样本 eval 通过 + 轨迹可审计
- **Phase 4（可选，1 天）:** checkpointer（SQLite→Redis）+ 中断恢复；退出条件：跨请求状态可恢复

### Technology Stack Recommendations

- **引入:** `langgraph`（1.2.x）、`langgraph-checkpoint`（Phase 4 配 sqlite 子包）
- **不引入:** LangGraph Platform、LangSmith 生产依赖、`create_agent` 黑盒抽象、llama-agents（已弃用）
- **保持不动:** 全部 Stage 契约、SSE 事件协议、Celery 队列、存储层、前端
- **升级注意:** langchain 生态将被带至 1.x，先验证 `LangChainRetrievalStage`

### Skill Development Requirements

- LangGraph 四件套（StateGraph / reducer / 条件边 / stream_mode）——官方 quickstart 1-2 天
- DashScope function calling 的 OpenAI 兼容用法——官方文档半天
- CRAG / Adaptive RAG 论文通读（2401.15884 优先）——理解 grade 节点的设计依据

### Success Metrics and KPIs

- **质量:** RAGAS faithfulness / answer relevancy 双路径对比不降；低质检索用例拒答准确率提升（Phase 2 目标）
- **延迟:** P50 总延迟增幅 < 30%（单跳场景）；TTFB 不回退
- **成本:** 平均 token/请求增幅可见且 < 2x（多跳样本除外）
- **行为:** hop 分布（单跳/多跳/拒答占比）、`tool_trace` 覆盖率 100%
- **叙事:** mermaid 架构图 + 双路径对比数据 = 作品集演示素材

---

## Research Synthesis

### Executive Summary

CloudBrief 支持副驾已完成混合检索（BM25 + 向量 → RRF → Rerank）、硬分支拒答、引用解析、时效提示与 GraphRAG 的建设，当前编排是 `ChatService.ask_stream` 中的手写线性流：检索参数写死、无分支、无重试、无多跳。引入 Agentic RAG 的本质，是把这条"固定管线"升级为"自适应管线"——而本调研核验的结论是：**这件事不需要重写，只需要平移加扩展。**

**推荐决策：采用 LangGraph StateGraph 作为编排层，以"图内确定性路由 + 节点内受限自主"为架构原则，按 Phase 0-4 五阶段渐进落地，总工期约 5-8 天。** 决策依据有三。其一，时机正确：LangGraph 1.0（2025-10）给出 API 稳定承诺，调研当日核验版本 1.2.9（2026-07-10），GitHub 37.3k stars 且当日仍有提交；对照组 LlamaIndex Workflows 2.22.2 活跃维护但核心包仍在 0.x 版本线。其二，项目条件成熟：`AbstractStage` 统一契约使每个 Stage 天然是图节点；`retrieval_adapter` 切换机制提供了现成的运行期开关模式；结构化 SSE 事件与 LangGraph 三种 stream_mode 存在干净映射（前端零改动）；GraphRAG shadow mode 提供了灰度先例；RAGAS 提供了回归护栏。其三，风险可控：拒答、权限、跳数终止保留在代码控制的条件边，native 路径永久保留，回滚是后台开关的秒级操作。

**Key Technical Findings:**

- 架构选型的心智模型：三方案的分水岭是控制流可见性——StateGraph 显式边 > Workflows 事件路由 > 手写代码路径，而本项目演进方向（多跳 + 工具化 + 灰度对照）持续增加分支与循环，显式图边际收益最高
- 学术模式到工程的映射：CRAG（arXiv 2401.15884）= Phase 2 的 grade 节点 + 改写重试边；Adaptive RAG 三档路由 = Phase 3 的 plan 节点；Self-RAG 思想借用、实现不借用（需微调，overkill）
- 集成核验的关键事实：DashScope 兼容模式原生支持 OpenAI 风格 function calling（与项目现有端点同源）；推荐路线 A（扩展 `ModelClient.chat` 的 tools 参数）保住 provider failover
- 权限红线：鉴权与 kb 权限校验必须在图入口之前完成，不能下沉为 Agent 可决策节点
- 最大实施风险是 R4：langgraph 会将 langchain 生态带至 1.x，升级后第一件事是验证现有 `LangChainRetrievalStage` 适配器

**Technical Recommendations:**

1. 立即执行 Phase 0（0.5 天）：`uv add langgraph langgraph-checkpoint` + `orchestration_mode` 设置项，行为零变化
2. Phase 1 做等价平移并用 RAGAS 证明无损，再让任何"智能"进图
3. Phase 2 先上 CRAG 化（改动最小、故事最强、收益可量化）
4. 不引入清单：LangGraph Platform、`create_agent` 黑盒、llama-agents（已弃用）、ReAct 全自主循环
5. 调研完成后用 `bmad-spec` 将结论蒸馏为 SPEC 契约，再走 epics/stories（复用 GraphRAG 线的成功路径）

### Table of Contents

1. 引言与方法论
2. 技术全景与架构分析（详见 Architectural Patterns and Design）
3. 实施方法与最佳实践（详见 Implementation Approaches）
4. 技术栈演进与趋势（详见 Technology Stack Analysis）
5. 集成与互操作模式（详见 Integration Patterns Analysis）
6. 性能与可扩展性分析
7. 安全与合规考量
8. 战略技术建议
9. 实施路线图与风险评估
10. 未来展望与创新机会
11. 调研方法论与来源核验
12. 附录与参考材料

### 1. 引言与方法论

**调研意义：** 2025-2026 年 RAG 工程的主线是"固定管线 → 图编排 + 受控自主"。LangChain/LangGraph 1.0（2025-10）标志编排层 API 进入冻结期；LangGraph 库自身保持高活跃（调研当日有提交）。对企业知识问答系统，自适应检索（按需检索、质量纠偏、多跳分解）是检索质量进入平台期后的下一个确定性收益点。对作品集项目，"显式状态图 + 受控自主 + 双路径对照"构成一个可验证、可演示、有学术依据的完整叙事。

**方法论：** 六步流程；事实核验四层——PyPI 官方元数据（版本/日期/依赖约束）、GitHub API（生态活跃度）、arXiv 原文（学术模式）、官方文档（功能与协议）；本地代码直读验证项目接缝；每条结论标注置信度（高/中高/中），"未见"型结论单独声明。

**目标达成：**

- ✅ 选型结论：LangGraph StateGraph，证据链完整（版本、生态、集成、架构四层）
- ✅ 落地路径：Phase 0-4 含退出条件，每阶段独立可交付
- ✅ 附带发现：llama-agents 弃用与 Workflows 存活的区分（避免被二手信息误导）；langgraph-checkpoint-redis 0.5.1 于调研前一日发布（Phase 4 可用但需观察）

### 2. 技术全景与架构分析

三种编排形态（显式状态图 / 事件驱动工作流 / 手写编排）的形态对比、CRAG 与 Self-RAG 的原文核验、自主性光谱（ReAct / Plan-Execute / 图内确定性路由）的选择论证，详见 **Architectural Patterns and Design** 章节。核心不变量：护栏即边——拒答阈值、时效检查、引用解析、权限校验的正确性不依赖 LLM 行为，这是双路径可对比评测的前提。

### 3. 实施方法与最佳实践

Strangler Fig 渐进迁移、阶段门采用、三层测试设计（Stage 单测 / 节点单测 / 图级路由断言）、prompt 资产化、shadow 灰度三级推进，详见 **Implementation Approaches and Technology Adoption** 章节。

### 4. 技术栈演进与趋势

全部版本事实经 PyPI 元数据核验（见附录证据表）。趋势判断：LangGraph 过 1.0 后采用风险显著下降；LlamaIndex Workflows 活跃但核心包 0.x；`llama-agents`（多 agent 部署，ALPHA 已弃用）与 `llama-index-workflows`（活跃）必须区分。详见 **Technology Stack Analysis** 章节。

### 5. 集成与互操作模式

六个真实接缝逐一核验：编排切换（`SettingMeta` 模式复用）、SSE 三模式映射（前端零改动）、工具调用（路线 A 扩 ModelClient）、状态持久化（SQLite→Redis 序列）、观测（`tool_trace` 落 `query_logs` + prometheus 标签）、权限（前置红线）。详见 **Integration Patterns Analysis** 章节。

### 6. 性能与可扩展性分析

_延迟预算:_ 每个 agentic 节点 +1 次 LLM 调用（经验量级 +0.5-2s，置信度：中）；`max_hops=2` 封顶；评估节点短输出；TTFB 由 generate 节点 token 流保住（CRAG 重试发生在生成之前）。
_并发:_ 同步 Stage 继续 `asyncio.to_thread` 包裹；多跳子问题可并行检索（置信度：中）。
_容量:_ 无新服务、无状态图单例，uvicorn 多 worker 安全（置信度：中高）；成本经 `tool_trace` 可见。
_Source: backend/app/services/chat_service.py ; https://docs.langchain.com_

### 7. 安全与合规考量

_访问控制:_ JWT 三通道解析保持在 API 层；kb 权限校验为图前门槛（`KbAccessStore`），agentic 路径不扩大任何数据可达面——工具集等价于现有管线能力的重新组合，不新增数据出口。
_注入面:_ 检索内容进 LLM 上下文是固有注入面，agentic 化后接触面变宽（改写/分解/评估节点）但性质不变；护栏为工具输出结构化、系统提示固定、评估节点只输出判定。
_审计:_ `tool_trace` 提供每次路由决策的可回放记录，满足企业内部系统的可解释要求；密钥管理沿用 `.env` + SecretStr 现状，无变化。
_Source: backend/app/services/chat_service.py ; backend/app/pipelines/generation.py_

### 8. 战略技术建议

_决策框架:_ 编排框架的选择标准按权重排序——控制流可审计性（企业护栏要求）> 与现有接缝的集成成本 > API 稳定性 > 生态工具 > 学习曲线。LangGraph 在前三项全胜。
_差异化定位:_ 本项目的 agentic 化不是"套框架"，而是三层演进的第三章（Native pipeline → LangChain adapter → Agentic StateGraph），且保留双路径可对比——这在叙事中把"会用框架"升级为"会做架构决策并能量化验证"。
_战略投入:_ 优先投入 `tool_trace` 可观测与 eval 集多跳扩充——前者是 agentic 功能上线的前置条件，后者是价值可度量的前提；两者都是一次性投入长期收益。

### 9. 实施路线图与风险评估

路线图（Phase 0-4，含工期与退出条件）与风险登记（R1-R6，含概率/影响/缓解）见 **Technical Research Recommendations** 章节。关键路径：Phase 0 → Phase 1 平移 → Phase 2 CRAG 化是价值拐点（首个可量化收益），Phase 3 多跳是能力拐点（首个 native 做不到的能力）。

### 10. 未来展望与创新机会

_近期（1-3 个月）:_ Phase 0-3 落地；eval 集多跳扩充；`tool_trace` 复盘驱动 prompt 迭代。
_中期（3-6 个月）:_ Phase 4 checkpointer 启用后，会话级记忆（跨轮次的检索策略延续）与人机协同中断点（高成本操作前确认）成为可选项；graph 工具与多跳结合（图谱多跳推理）是本项目独有的深化方向——Neo4j 子图已是现成资产。
_远期:_ 多 agent 协作（检索 agent + 生成 agent 分工）技术上可行，但对单库问答场景价值密度低，不建议作为目标，仅作知识储备。
_创新机会:_ 双路径对照数据（同 eval 集、同 query_logs 口径）本身可产出一份高质量的工程博客/作品集附件——"Agentic RAG 到底值不值"的量化回答比功能本身更稀缺。

### 11. 调研方法论与来源核验

**主要来源（一手）:**

- PyPI 官方元数据：langgraph 1.2.9、langchain 1.3.13、langchain-openai 1.3.5、llama-index-workflows 2.22.2、llama-index 0.14.23、langgraph-checkpoint 4.1.1、-sqlite 3.1.0、-postgres 3.1.0、-redis 0.5.1、langsmith 0.10.4（均含发布日期，见附录）
- GitHub API：langgraph 37,334 stars / 6,254 forks / pushed 2026-07-15；llama_index 50,860 stars / 7,754 forks / pushed 2026-07-13
- arXiv 原文：2401.15884（CRAG，2024-01-29）、2310.11511（Self-RAG，2023-10-17）
- 阿里云官方文档：qwen function calling（compatible-mode/v1/chat/completions 支持 tools）
- LangGraph 官方文档：streaming how-to（stream_mode 五值、get_stream_writer）、types reference
- 本地代码直读：config.py、settings_service.py、chat_service.py、model_client.py、generation.py、retrieval.py、base.py、tests/

**检索查询记录:** "LangGraph 1.0 release 2025 stable"、"langgraph latest version pypi 2026"、"LlamaIndex Workflows 2.0 standalone package deprecated"、"LangGraph streaming stream_mode messages updates custom astream"、"LangChain 1.x bind_tools ToolNode"、"LlamaIndex workflows 2.0 stream_events handler"、"GraphRAG agentic RAG multi-hop integration"、"Corrective RAG arxiv 2401.15884"、"Self-RAG arxiv 2310.11511"、PyPI JSON API × 10、GitHub API × 2、arXiv abs 页 × 2、阿里云文档页抓取 × 1。

**质量保证与局限:**

- 全部版本/日期类事实为 PyPI/GitHub/arXiv 一手数据，置信度高
- "未见"型结论（LlamaIndex 无官方 saver 生态、LlamaIndex 无现成 token 级流模式）置信度中，存在文档遗漏可能
- Adaptive RAG 论文编号（2403.14403）未逐字核验，置信度中
- 延迟数字（+0.5-2s/节点）为经验量级而非实测，置信度中；Phase 1 后应以本项目实测校准
- llama-agents 弃用状态来自 deepwiki 二手源，置信度中高；不影响主结论

### 12. 附录与参考材料

**版本证据表（PyPI 元数据，调研日 2026-07-15 核验）:**

| 包 | 版本 | 发布日期 | Python 要求 | 用途 |
|---|---|---|---|---|
| langgraph | 1.2.9 | 2026-07-10 | >=3.10 | 编排框架（推荐引入） |
| langchain | 1.3.13 | 2026-07-10 | >=3.10 | 生态基座（将被带升级） |
| langchain-openai | 1.3.5 | 2026-07-10 | — | 路线 B 备选 |
| langgraph-checkpoint | 4.1.1 | 2026-05-22 | — | 持久化基座（Phase 4） |
| langgraph-checkpoint-sqlite | 3.1.0 | 2026-05-12 | — | 首选持久化（Phase 4） |
| langgraph-checkpoint-postgres | 3.1.0 | 2026-05-12 | — | 生产选项（本项目暂缓） |
| langgraph-checkpoint-redis | 0.5.1 | 2026-07-14 | — | 复用现有 Redis（0.x，观察） |
| llama-index-workflows | 2.22.2 | 2026-06-30 | >=3.10 | 对照组（未选） |
| llama-index | 0.14.23 | 2026-06-24 | >=3.10 | 对照组核心包（0.x） |
| langsmith | 0.10.4 | 2026-07-14 | — | 开发期 trace（可选） |

**参考文献:**

- Yan et al., "Corrective Retrieval Augmented Generation", arXiv:2401.15884, 2024-01-29
- Asai et al., "Self-RAG: Learning to Retrieve, Generate, and Critique through Self-Reflection", arXiv:2310.11511, 2023-10-17
- LangGraph 官方文档：https://docs.langchain.com（streaming、persistence、types reference）
- LlamaIndex Workflows 文档：https://docs.llamaindex.ai/en/stable/module_guides/workflow/
- 阿里云百炼 Function Calling：https://help.aliyun.com/zh/model-studio/qwen-function-calling
- LangChain Changelog（1.x 发布记录）：https://changelog.langchain.com

---

## Technical Research Conclusion

### 关键发现总结

本项目引入 Agentic RAG 的正确姿势是"平移 + 扩展"：LangGraph StateGraph 承接现有 Stage 契约与 SSE 协议，五阶段渐进落地，护栏留在代码边，双路径永久并行。选型证据链覆盖版本（PyPI）、生态（GitHub）、学术（arXiv）、集成（本地代码 + 官方文档）四层。

### 战略影响评估

对工程：检索质量进入平台期后的下一个确定性收益点被解锁，且以可审计、可回滚的方式。对作品集：完成"固定管线 → 自适应管线"的三层演进叙事，并附带双路径量化对照数据——这在同类项目中的稀缺性高于功能本身。

### 下一步建议

1. 新开上下文窗口运行 `bmad-spec`，将本报告蒸馏为 SPEC.md 契约（复用 GraphRAG 线 TR→spec→epics 的成功路径）
2. spec 定稿后运行 `bmad-create-epics-and-stories` 拆分 Phase 0-2 为可执行 story
3. Phase 0 开工前补一件事：升级 langchain 生态后先跑 `LangChainRetrievalStage` 验证（风险 R4）

---

**Technical Research Completion Date:** 2026-07-15
**Research Period:** 当日全面核验（所有版本/生态数据为 2026-07-15 实时数据）
**Source Verification:** 关键事实经多源交叉核验，置信度逐条标注
**Technical Confidence Level:** 高（核心结论基于一手来源）

_本文档为 CloudBrief 支持副驾 Agentic RAG 编排选型的权威技术参考，可直接作为 `bmad-spec` 的输入。_
