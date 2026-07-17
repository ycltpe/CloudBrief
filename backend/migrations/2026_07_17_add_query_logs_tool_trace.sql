-- 2026_07_17_add_query_logs_tool_trace.sql
-- Agentic RAG 编排轨迹：query_logs 新增 tool_trace JSON 列，支持 hop 分布、节点延迟、路由回放等审计。

ALTER TABLE query_logs
ADD COLUMN tool_trace JSON NULL
COMMENT 'agentic 图执行轨迹，每个节点包含 node/latency_ms 等指标';
