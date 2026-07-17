from prometheus_client import Counter, Gauge, Histogram, generate_latest

# 检索
RETRIEVAL_LATENCY = Histogram(
    "rag_retrieval_latency_ms",
    "端到端检索耗时",
    ["adapter", "kb_id", "fallback", "orchestration_mode"],
    buckets=[10, 50, 100, 200, 500, 1000, 2000, 5000, 10000],
)
RECALL_COUNT = Histogram(
    "rag_recall_count",
    "检索返回 chunk 数量",
    ["adapter", "kb_id", "fallback", "orchestration_mode"],
    buckets=[1, 2, 5, 10, 20, 50, 100],
)
RERANK_MAX_SCORE = Gauge(
    "rag_rerank_max_score",
    "最终进入生成的最高分",
    ["adapter", "kb_id", "fallback", "orchestration_mode"],
)

# 生成
GENERATION_LATENCY = Histogram(
    "rag_generation_latency_ms",
    "生成耗时",
    ["provider", "model", "orchestration_mode"],
    buckets=[100, 500, 1000, 2000, 5000, 10000, 20000, 30000],
)
REFUSAL_RATE = Counter(
    "rag_refusal_total",
    "硬分支拒答次数",
    ["reason", "kb_id", "orchestration_mode"],
)

# 错误
ERROR_TOTAL = Counter(
    "rag_error_total",
    "错误总数",
    ["code", "component"],
)

# 模型健康
MODEL_UP = Gauge(
    "rag_model_up",
    "模型/服务健康状态",
    ["provider", "model"],
)

# 索引任务
INDEX_TASK_TOTAL = Counter(
    "rag_index_task_total",
    "索引任务总数",
    ["task_type", "kb_id", "status"],
)

# HTTP
HTTP_REQUESTS_TOTAL = Counter(
    "rag_http_requests_total",
    "HTTP 请求总数",
    ["method", "path", "status_code"],
)
HTTP_REQUEST_DURATION = Histogram(
    "rag_http_request_duration_ms",
    "HTTP 请求耗时",
    ["method", "path"],
    buckets=[10, 50, 100, 200, 500, 1000, 2000, 5000],
)


def metrics_response() -> bytes:
    return generate_latest()
