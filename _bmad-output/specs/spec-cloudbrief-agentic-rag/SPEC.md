---
id: SPEC-cloudbrief-agentic-rag
companions:
  - phased-rollout.md
  - risk-register.md
  - ../../planning-artifacts/research/technical-agentic-rag-orchestration-frameworks-research-2026-07-15.md
sources: []
---

> **Canonical contract.** This SPEC and the files in `companions:` are the complete, preservation-validated contract for what to build, test, and validate. Source documents listed in frontmatter are for traceability only — consult them only if you need narrative rationale or prose color this contract intentionally omits.

# CloudBrief 问答链路引入 Agentic RAG 编排（LangGraph StateGraph，双路径并行）

## Why

现有问答链路是 `ChatService.ask_stream` 中的手写线性流：检索参数写死、无分支、无重试、无多跳。检索质量进入平台期后，自适应检索（按需检索、质量纠偏、多跳分解）是下一个确定性收益点。这是一个机会型 + 痛点型复合驱动力：企业用户受低质检索漏答与无法处理复杂多跳问题所限（痛点），而 LangGraph 1.0（2025-10）API 冻结、调研日核验 1.2.9 活跃维护，使编排层引入风险显著下降（机会）。项目自身的五个接缝——Stage 统一契约、`retrieval_adapter` 开关先例、结构化 SSE 协议、GraphRAG shadow 灰度先例、RAGAS 评测链路——使本次引入为"平移 + 扩展"而非重写。双路径对照数据同时构成作品集的核心叙事资产。

受影响方：企业用户（获得质量纠偏与多跳问答能力）；管理员（获得编排模式开关与轨迹可观测）；作品集受众（获得"固定管线 → 自适应管线"的可量化架构决策叙事）。

## Capabilities

- **CAP-1**
  - **intent:** 管理员可在运行期切换编排模式（native / langchain / agentic，默认 native）。
  - **success:** 后台切换即时生效；native 默认下行为与现状完全一致；`config_snapshot` 记录于 `query_logs`。
- **CAP-2**
  - **intent:** agentic 模式下系统以状态图执行与现有流程等价的问答（改写 → 检索 → 生成），SSE 协议不变。
  - **success:** 现有 pytest 全绿；同一 RAGAS eval 集上 agentic 的 faithfulness / answer relevancy 与 native 持平（Phase 1 退出条件）。
- **CAP-3**
  - **intent:** 系统可评估检索质量并在低分时改写查询重试（max_hops=2），拒答判定保持代码控制的硬分支。
  - **success:** eval 集上低质检索用例的回答率 / 拒答准确率改善可量化（Phase 2 退出条件）。
- **CAP-4**
  - **intent:** 系统可按查询复杂度三档路由（直接检索 / 多跳分解 / 图谱增强），并将检索作为工具调用。
  - **success:** eval 集多跳样本通过；每次路由决策与工具调用序列可从 `query_logs` 回放审计（Phase 3 退出条件）。
- **CAP-5**
  - **intent:** 系统记录每次请求的编排轨迹（路由决策、工具调用序列、跳数、各跳 max_score、模型/延迟/token）并纳入现有指标管道。
  - **success:** `tool_trace` 覆盖率 100%；prometheus 按 `orchestration_mode` 标签可对比双路径延迟分布。
- **CAP-6**
  - **intent:** 当 agentic 路径方向无法确认、需要中断-检查-恢复能力辅助决策时，系统可跨请求持久化编排状态并支持中断恢复（Phase 4，触发式启用；无此信号则不做）。
  - **success:** 触发条件出现时，checkpointer 启用后跨请求状态可恢复（Phase 4 退出条件）。

## Constraints

- 护栏由代码控制的条件边实现：拒答阈值、权限校验、跳数终止、时效检查的正确性不依赖 LLM 行为。
- JWT 鉴权与 kb 权限校验在图入口之前完成，不下沉为 Agent 可决策节点，避免路由自由度变成越权面。
- SSE 六事件协议（chunk / citations / status / done / error / sources）与前端消费逻辑不变；编排逻辑全部在 Python 后端，前端只消费 SSE。
- 不新增服务：LangGraph 以库形态嵌入现有 FastAPI 进程，docker compose 清单与 Celery 队列不变。
- native 路径永久保留；回滚为后台开关秒级切换，无数据迁移。
- 工具调用走路线 A：扩展 `ModelClient.chat(tools=...)`，保住 provider failover / 重试 / 统一日志；不引入 langchain-openai ToolNode 路线。
- 检索循环 max_hops=2 封顶，第二跳起 top_k 减半；plan / grade 节点低 temperature + 短 max_tokens + JSON 结构化输出（可降级到便宜模型档）。
- Stage 契约与现有 Stage 测试不动；langchain 生态被带至 1.x 后先验证 `LangChainRetrievalStage` 再继续后续阶段。
- 会话消息继续存 MySQL；checkpointer 只存编排状态，`thread_id == conversation_id`，无双写真相源。
- 图 State 复用现有 `RetrievalResult` Pydantic 契约，不加 DTO 转换层；StateGraph 定义集中于 `app/orchestration/`，编译为模块级单例。

## Non-goals

- ReAct 全自主循环（LLM 自主决定何时检索、检索什么、何时停）不作为目标架构。
- 不引入 LangGraph Platform（托管 / 自部署 server），不引入生产环境 LangSmith 依赖。
- 不采用 `create_agent` 黑盒抽象，不做多 agent 分工协作（检索 agent + 生成 agent）。
- 不做 Self-RAG 式 reflection tokens 微调（思想借用、实现不借用）；不引入 llama-agents（已弃用）。
- 前端无改造：不新增页面、不改交互。

## Success signal

同一 RAGAS eval 集双路径对照：agentic 的 faithfulness / answer relevancy 不低于 native，低质检索用例拒答准确率提升，多跳样本通过；P50 总延迟增幅 < 30%（单跳场景）、TTFB 不回退、平均 token / 请求增幅 < 2x（多跳样本除外）；`tool_trace` 覆盖率 100% 且 hop 分布（单跳 / 多跳 / 拒答占比）可见。

## Assumptions

- 每个 agentic 节点 +0.5-2s 延迟为经验量级（置信度中），Phase 1 后以本项目实测校准。
- Adaptive RAG 论文编号（arXiv 2403.14403）未逐字核验，三档路由设计依据工程需要而非论文细节。
