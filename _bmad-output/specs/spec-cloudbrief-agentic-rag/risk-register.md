# 风险登记（R1-R6）

| ID | 风险 | 概率 / 影响 | 缓解 |
|---|---|---|---|
| R1 | LLM 路由误判 | 中 / 中 | `query_logs` 采样复盘 + prompt 迭代；拒答硬分支兜底，误判不会击穿拒答口径 |
| R2 | 延迟膨胀 | 中 / 中 | max_hops=2、评估节点短输出、预算配置化；TTFB 由 generate 节点 token 流保住（CRAG 重试发生在生成之前） |
| R3 | token 成本上升 | 高 / 低 | 节点精简 + 成本入 `tool_trace`，月度审视 |
| R4 | langchain 0.2→1.x 升级破坏现有 LC 适配器 | 中 / 中 | 升级后首先跑 `LangChainRetrievalStage` 路径验证（Phase 0 内完成）；必要时锁定 langchain 版本区间 |
| R5 | 双路径行为漂移 | 低 / 中 | 同一 eval 集双跑 + shadow 对照；拒答口径共享同一边逻辑 |
| R6 | langgraph-checkpoint-redis 0.x 成熟度 | 低 / 低 | Phase 4 才引入，先 SQLite 验证 |
