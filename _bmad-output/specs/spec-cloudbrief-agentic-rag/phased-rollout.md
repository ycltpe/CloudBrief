# 分阶段落地路线（Phase 0-4）

Strangler Fig 渐进迁移：agentic 路径与 native / langchain 路径并行，后台 `orchestration_mode` 开关切流。每阶段独立可交付、可演示；每阶段以 shadow 对照先行、RAGAS 回归守门，未过退出条件不进入下一阶段。总工期约 5-8 天。

| Phase | 工期 | 内容 | 退出条件 |
|---|---|---|---|
| 0 | 0.5 天 | `uv add langgraph langgraph-checkpoint`；新增 `orchestration_mode` 设置项（SettingMeta 注册 + 后台可见）；升级 langchain 生态至 1.x 后**首先**跑通 `LangChainRetrievalStage` 验证（风险 R4） | 开关可切换且无行为变化 |
| 1 | 1-2 天 | 线性平移：`ask_stream` 流程建成等价 StateGraph（rewrite→retrieve→generate）；SSE 三模式映射（messages→chunk、updates→status、custom→sources） | 现有测试全绿 + RAGAS 基线与 native 持平 |
| 2 | 1-2 天 | CRAG 化：加 `grade` 节点 + 改写重试边（max_hops=2）；工程版 CRAG——LLM 轻量评估替代论文训练版评估器 | 低质检索用例的回答率 / 拒答准确率改善可量化 |
| 3 | 2-3 天 | 工具化 + 多跳：`plan` 节点三档路由（直检 / 多跳 / 图谱）；`ModelClient.chat` 扩 tools 参数（路线 A）；`tool_trace` 落 `query_logs` | 多跳样本 eval 通过 + 轨迹可审计 |
| 4（触发式） | 1 天 | 触发条件：agentic 路径方向无法确认、需要中断-检查-恢复能力辅助决策时启动，无此信号则不做。checkpointer（`langgraph-checkpoint-sqlite` 零运维起步，需要分布式再迁 `-redis` 复用现有 Redis 6381）+ 中断恢复 | 跨请求状态可恢复 |

## 测试与评测守门

- Stage 单测：现有测试不动（Stage 契约不变是不变量）。
- 节点单测：LLM 调用 stub 化（monkeypatch ModelClient），断言每个图节点的状态增量。
- 图级测试：固定 LLM 响应序列，断言条件边路由（低分→重试边、空检索→拒答边、hop 上限→终止边）；checkpointer 用 InMemorySaver 注入。
- 评测守门：同一 RAGAS eval 集双路径跑分（faithfulness / answer relevancy / 拒答准确率）；eval 集需补充多跳问题样本。
- 多跳样本（通用合成方案）：LLM 从现有知识库相关 chunk 对生成需两跳推理的问题，人工抽检入 eval 集；首期 30 条两跳样本 + 10 条直检对照，后续从 `query_logs` 真实多跳问题持续增补。

## 灰度与回滚

复用 GraphRAG shadow 模式三级推进：shadow 旁路对照 → 后台开关切流 → `query_logs` 对比。回滚 = 后台切回 native，秒级生效，无数据迁移。

## 集成要点

- graph 工具沿用 `GraphSchemaStore` 的 per-kb 开关（enabled / shadow_mode）决定是否向 plan 节点提供图谱档，不新增图访问控制面。
- plan / grade 节点 prompt 按 `QueryRewriteStage` 同模式资产化管理（独立 stage 文件 + 模板常量），随 `query_logs` 采样复盘迭代。
- 同步 Stage 在图节点中继续 `asyncio.to_thread` 包裹；多跳子问题可并行检索；图编译单例无共享可变状态，uvicorn 多 worker 安全。
- 前置技能准备：LangGraph 四件套（StateGraph / reducer / 条件边 / stream_mode，约 1-2 天）；DashScope function calling OpenAI 兼容用法（约半天）；CRAG 论文 arXiv 2401.15884 通读。

## 版本锚点（调研日 2026-07-15 PyPI 核验）

langgraph 1.2.9；langgraph-checkpoint 4.1.1；langgraph-checkpoint-sqlite 3.1.0；langgraph-checkpoint-redis 0.5.1（0.x，成熟度观察中，Phase 4 才考虑）；langchain 将被带至 1.3.x。
