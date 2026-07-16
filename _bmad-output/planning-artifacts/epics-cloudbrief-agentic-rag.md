---
stepsCompleted:
  - step-01-validate-prerequisites
  - step-02-design-epics
inputDocuments:
  - ../specs/spec-cloudbrief-agentic-rag/SPEC.md
  - ../specs/spec-cloudbrief-agentic-rag/phased-rollout.md
  - ../specs/spec-cloudbrief-agentic-rag/risk-register.md
updated: 2026-07-16
---

# CloudBrief Agentic RAG 编排 - Epic & Story 分解

## Overview

This document provides the complete epic and story breakdown for CloudBrief Agentic RAG 编排增量, decomposing the requirements from the SPEC kernel, phased rollout plan, and risk register into implementable stories.

## Requirements Inventory

### Functional Requirements

FR1: 管理员可在运行期切换编排模式（native / langchain / agentic，默认 native），切换即时生效，配置快照记入 `query_logs.config_snapshot`。
FR2: agentic 模式下系统以状态图执行与现有流程等价的问答（改写 → 检索 → 生成），SSE 六事件协议（chunk / citations / status / done / error / sources）与前端消费逻辑不变。
FR3: 系统可评估检索质量（grade 节点），低分时改写查询并重试（max_hops=2），拒答判定保持代码控制的硬分支。
FR4: 系统可按查询复杂度三档路由（直接检索 / 多跳分解 / 图谱增强）（plan 节点）。
FR5: 检索可作为工具被调用：`ModelClient.chat` 扩展 tools 参数（路线 A），保住 provider failover / 重试 / 统一日志。
FR6: 系统记录每次请求的编排轨迹 `tool_trace`（路由决策、工具调用序列、跳数、各跳 max_score、模型/延迟/token）落 `query_logs`。
FR7: prometheus 指标增加 `orchestration_mode` 标签，双路径延迟分布可在 dashboard 对比。
FR8: 触发条件出现时（agentic 路径方向无法确认、需中断-检查-恢复辅助决策），系统可跨请求持久化编排状态（checkpointer，SQLite 起步可迁 Redis）并支持中断恢复。

### NonFunctional Requirements

NFR1: 护栏由代码控制的条件边实现：拒答阈值、权限校验、跳数终止、时效检查的正确性不依赖 LLM 行为。
NFR2: JWT 鉴权与 kb 权限校验在图入口之前完成，不下沉为 Agent 可决策节点。
NFR3: 质量门槛：同一 RAGAS eval 集上 agentic 的 faithfulness / answer relevancy 不低于 native；低质检索用例拒答准确率提升。
NFR4: 延迟预算：P50 总延迟增幅 < 30%（单跳场景）；TTFB 不回退。
NFR5: 成本预算：平均 token/请求增幅 < 2x（多跳样本除外）；max_hops=2 封顶，第二跳起 top_k 减半；plan / grade 节点低 temperature + 短 max_tokens + JSON 结构化输出。
NFR6: 兼容性：Stage 契约与现有 Stage 测试不动；图 State 复用现有 `RetrievalResult` Pydantic 契约，无 DTO 转换层。
NFR7: 部署形态：不新增服务，LangGraph 以库形态嵌入现有 FastAPI 进程，docker compose 清单与 Celery 队列不变；图编译单例无共享可变状态，uvicorn 多 worker 安全。
NFR8: 回滚：native 路径永久保留，回滚为后台开关秒级切换，无数据迁移。

### Additional Requirements

- `uv add langgraph langgraph-checkpoint`；langchain 生态将被带至 1.x，升级后首先验证 `LangChainRetrievalStage`（风险 R4，Phase 0 内完成）。
- StateGraph 定义集中于新目录 `app/orchestration/`，编译为模块级单例。
- 三层测试设计：Stage 单测不动；节点单测 monkeypatch ModelClient 断言状态增量；图级测试固定 LLM 响应序列断言条件边路由（低分→重试边、空检索→拒答边、hop 上限→终止边）；checkpointer 测试用 InMemorySaver。
- 评测守门：同一 RAGAS eval 集双路径跑分；多跳样本按通用合成方案扩充（LLM 从现有 KB 相关 chunk 对合成两跳问题 + 人工抽检，首期 30 条两跳 + 10 条直检对照，后续从 query_logs 真实多跳问题增补）。
- 灰度：复用 GraphRAG shadow 模式三级推进（shadow 旁路对照 → 后台开关切流 → `query_logs` 对比）。
- graph 工具沿用 `GraphSchemaStore` 的 per-kb 开关（enabled / shadow_mode）决定是否向 plan 节点提供图谱档。
- plan / grade 节点 prompt 按 `QueryRewriteStage` 同模式资产化管理（独立 stage 文件 + 模板常量）。
- 同步 Stage 在图节点中继续 `asyncio.to_thread` 包裹；多跳子问题可并行检索。
- 会话消息继续存 MySQL；checkpointer 只存编排状态，`thread_id == conversation_id`，无双写真相源。
- 前置技能准备：LangGraph 四件套（StateGraph / reducer / 条件边 / stream_mode，约 1-2 天）；DashScope function calling OpenAI 兼容用法（约半天）；CRAG 论文 arXiv 2401.15884 通读。

### UX Design Requirements

无（本增量明确"前端无改造"为非目标：不新增页面、不改交互；编排价值全部经后端与可观测数据体现）。

### FR Coverage Map

FR1: Epic 1 — 编排模式运行期开关
FR2: Epic 1 — 状态图等价平移
FR3: Epic 2 — grade 节点 + 改写重试（max_hops=2）
FR4: Epic 3 — plan 节点三档路由
FR5: Epic 3 — 检索工具化（ModelClient 路线 A）
FR6: Epic 3 — tool_trace 编排轨迹
FR7: Epic 1 — prometheus orchestration_mode 标签
FR8: Epic 4 — checkpointer 跨请求持久化 + 中断恢复（触发式）

## Epic List

### Epic 1: 编排基座与无损平移（Phase 0-1）
引入 langgraph 依赖与 orchestration_mode 开关，将 ask_stream 线性流平移为等价 StateGraph（rewrite→retrieve→generate），SSE 三模式映射，prometheus 加 orchestration_mode 标签；升级 langchain 1.x 后先验证 LangChainRetrievalStage。管理员获得可灰度、可秒级回滚的 agentic 模式基座，RAGAS 证明与 native 无损持平。
**FRs covered:** FR1, FR2, FR7

### Epic 2: 检索质量纠偏（Phase 2，CRAG 化）
图内加入 grade 节点与改写重试边（max_hops=2），拒答保持代码硬分支。企业用户在低质检索场景获得纠偏后更准的回答与更准的拒答——首个可量化收益。
**FRs covered:** FR3

### Epic 3: 自适应路由与多跳工具化（Phase 3）
plan 节点三档路由（直检/多跳分解/图谱增强），检索工具化（ModelClient 路线 A），tool_trace 落 query_logs。企业用户可问复杂多跳问题（首个 native 做不到的能力）；运营可回放审计每次路由决策。
**FRs covered:** FR4, FR5, FR6

### Epic 4: 编排状态持久化与中断恢复（Phase 4，触发式）
触发条件出现时（agentic 路径方向无法确认、需中断-检查-恢复辅助决策）引入 checkpointer（SQLite→Redis）与中断恢复。无触发信号则不实施。
**FRs covered:** FR8

<!-- Repeat for each epic in epics_list (N = 1, 2, 3...) -->

## Epic 1: 编排基座与无损平移（Phase 0-1）

引入 langgraph 依赖与 orchestration_mode 开关，将 ask_stream 线性流平移为等价 StateGraph（rewrite→retrieve→generate），SSE 三模式映射，prometheus 加 orchestration_mode 标签；升级 langchain 1.x 后先验证 LangChainRetrievalStage。管理员获得可灰度、可秒级回滚的 agentic 模式基座，RAGAS 证明与 native 无损持平。

### Story 1.1: 引入 LangGraph 依赖并验证 langchain 1.x 兼容性

As a 后端开发,
I want 通过 uv 引入 langgraph 与 langgraph-checkpoint，并验证 langchain 生态升至 1.x 后现有 LangChainRetrievalStage 行为不变,
So that 编排框架落地的第一件事就消除最大实施风险（R4），后续图开发站在稳定基座上。

**Acceptance Criteria:**

**Given** backend 现有 pyproject.toml 声明 `langchain>=0.2.0`
**When** 执行 `uv add langgraph langgraph-checkpoint` 并同步环境
**Then** langgraph（1.2.x）进入依赖，langchain 生态解析至 1.x，`uv run ruff check .` 通过
**And** 现有 pytest 全部通过；`LangChainRetrievalStage` 相关验证确认 retrieval_adapter=langchain 路径检索行为与升级前一致；若发现破坏，锁定 langchain 版本区间并在 spec memlog 记录决策

### Story 1.2: 新增 orchestration_mode 运行期开关

As a 管理员,
I want 在系统设置中切换编排模式（native / langchain / agentic，默认 native）并即时生效,
So that 我可以随时控制问答链路使用哪套编排，并无成本回滚。

**Acceptance Criteria:**

**Given** 系统设置模块已有 SettingMeta 注册机制（DB 优先 / .env 回退）
**When** 注册 `orchestration_mode` 设置项（native / langchain / agentic，默认 native）
**Then** 管理后台可见并可修改该设置，修改后新会话按所选模式执行且无需重启
**And** `query_logs.config_snapshot` 包含 orchestration_mode 值；默认 native 下现有问答行为与现状完全一致（回归测试通过）

### Story 1.3: 定义图 State 与 StateGraph 骨架

As a 后端开发,
I want 在 `app/orchestration/` 中定义复用现有 RetrievalResult 契约的图 State，以及 rewrite→retrieve→generate 线性 StateGraph（编译为模块级单例）,
So that 后续纠偏节点与路由边可以在稳定的图骨架上增量扩展，且 Stage 契约与现有测试不受影响。

**Acceptance Criteria:**

**Given** 现有 Stage 统一契约（AbstractStage）与 RetrievalResult Pydantic 模型
**When** 定义图 State（TypedDict + reducer，检索结果字段直接复用 RetrievalResult）与三节点线性图，节点内部委托现有 Stage 执行（同步 Stage 以 asyncio.to_thread 包裹）
**Then** 图编译为模块级单例，无共享可变状态，uvicorn 多 worker 下安全
**And** 节点单测（monkeypatch ModelClient）断言各节点状态增量正确；现有 Stage 测试零改动通过

### Story 1.4: agentic 模式端到端接入与 SSE 三模式映射

As a 企业用户,
I want 在 orchestration_mode=agentic 时获得与现状完全一致的流式问答体验（含来源、引用、拒答）,
So that 我不感知底层编排方式的变化。

**Acceptance Criteria:**

**Given** Story 1.3 的图骨架与 Story 1.2 的开关
**When** ChatService 按 orchestration_mode 组装 AgentGraphRunner，图通过 astream 输出并按映射转换（messages→chunk、updates→status、custom→sources、图结束→citations+done）
**Then** SSE 六事件协议（chunk / citations / status / done / error / sources）与事件负载结构不变，现有前端零改动即可正常消费
**And** JWT 鉴权与 kb 权限校验在图入口之前完成；拒答、引用解析、时效检查行为与 native 一致；TTFB 与 native 相比不回退

### Story 1.5: 双路径观测与 RAGAS 无损验证

As a 运营/管理员,
I want prometheus 指标按 orchestration_mode 区分，并用同一 RAGAS eval 集对双路径跑分,
So that 我能量化证明 agentic 模式与 native 质量持平，为后续灰度切流提供数据依据（Phase 1 退出条件）。

**Acceptance Criteria:**

**Given** agentic 模式已可端到端运行
**When** 为现有检索/生成延迟与拒答率指标增加 orchestration_mode 标签，并以同一 eval 集分别跑 native 与 agentic
**Then** dashboard 可按标签对比双路径延迟分布
**And** RAGAS faithfulness / answer relevancy 双路径持平（不劣于 native）；图级测试（固定 LLM 响应序列断言条件边路由，如空检索→拒答边）通过；全部 pytest 通过

<!-- End story repeat -->
