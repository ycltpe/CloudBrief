# Phase 3 子方案：监控与 Fallback 机制

## 1. 现状与目标

当前系统已在部分环节具备初步的容错与日志能力：

- `ModelClient` 对 Embedding / LLM 调用做了 3 次指数退避重试（仅针对网络/超时类异常）。
- `RerankingStage` 在重排服务不可用或返回空分时，已能回退到 RRF 融合分数。
- `GenerationPipeline` 实现了硬分支拒答，并在 GraphRAG 获取失败时降级为普通向量检索生成。
- `indexing.py` 已按步骤记录 `duration_ms` 与状态，并通过 Redis Pub/Sub 推送给前端。
- `logging_config.py` 已配置结构化 JSON 日志与 `request_id` 中间件。

但仍存在明显缺口：缺少统一指标暴露、存储层/Milvus 异常未做降级、LLM 超时无用户侧兜底、告警体系缺失、错误码不统一。本子方案的目标是在不破坏现有主流程的前提下，补齐**可观测性、分级告警、全链路降级**三项能力。

---

## 2. 关键监控指标

| 指标类别 | 指标名（Prometheus/OpenTelemetry） | 类型 | 说明 |
|---|---|---|---|
| **检索延迟** | `rag_retrieval_latency_ms` | Histogram | 端到端检索耗时，标签：`adapter=native\|langchain`、`fallback=true\|false` |
| **召回数** | `rag_recall_count` | Histogram/Gauge | 检索返回 chunk 数量，标签同上 |
| **重排分数** | `rag_rerank_max_score` | Gauge | 最终进入生成的最高分；`fallback=true` 时代表 RRF 分数 |
| **拒答率** | `rag_refusal_rate` | Counter/Gauge | 硬分支拒答次数 / 总问答次数 |
| **生成延迟** | `rag_generation_latency_ms` | Histogram | 从生成输入到首 token / 完整答案耗时 |
| **错误率** | `rag_error_total` | Counter | 按错误码聚合，如 `RETRIEVAL_ERROR`、`LLM_TIMEOUT`、`MILVUS_ERROR` |
| **模型可用性** | `rag_model_up` | Gauge | 各模型/服务健康状态，标签：`provider=dashscope\|local`、`model=embed\|rerank\|llm` |
| **索引任务成功率** | `rag_index_task_success_rate` | Gauge | 最近 1h/24h 成功任务占比，按 `task_type=rebuild\|single\|graph` 拆分 |

---

## 3. 指标采集方式

### 3.1 结构化日志（已有基础）

所有管线阶段统一输出 JSON 日志，关键字段固定：

```json
{
  "event": "retrieval_completed",
  "request_id": "uuid",
  "latency_ms": 123,
  "recall_count": 5,
  "max_score": 0.81,
  "is_fallback": false,
  "adapter": "native",
  "error_code": null
}
```

接入点：

- `RetrievalPipeline.retrieve()`：记录 `retrieval_started` / `retrieval_completed` / `retrieval_failed`。
- `GenerationPipeline.generate()` / `generate_stream()`：记录 `generation_started` / `generation_completed` / `generation_failed`。
- `ChatService.ask()` / `ask_stream()`：记录 `chat_answer_generated`（已存在，补充 `latency_ms`、`is_fallback`）。
- `ModelClient._log_call()`：已记录 `embed_success/failed`、`chat_success/failed`，补充 `provider`、`model` 标签。
- `indexing.py` 的 `_publish_step()`：已记录各阶段耗时，直接作为指标数据源。

### 3.2 FastAPI 中间件

在 `app/main.py` 中新增 `MetricsMiddleware`，统一采集 HTTP 层指标：

- 请求总量 `rag_http_requests_total`（标签：`method`、`path`、`status_code`）。
- 请求耗时 `rag_http_request_duration_ms`。
- 异常请求自动附加 `error_code` 到日志上下文。

实现要点：

```python
@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    duration = (time.perf_counter() - start) * 1000
    # 仅统计 chat / index / eval 等核心接口
    labels = {"path": request.url.path, "status": response.status_code}
    HTTP_DURATION.observe(duration, labels)
    return response
```

### 3.3 Prometheus / OpenTelemetry 暴露

- 新增依赖 `prometheus-client`。
- 在 `app/api/metrics.py` 暴露 `/metrics` 路由，供 Prometheus 抓取。
- 在 `app/clients/model_client.py`、`app/pipelines/retrieval.py`、`app/pipelines/generation.py` 中埋入 Counter / Histogram / Gauge。
- （可选进阶）引入 `opentelemetry-instrumentation-fastapi` + OTLP exporter，将 trace 推送到 Jaeger/Tempo，与 `request_id` 对齐。

### 3.4 数据库持久化表

新增 `monitoring_metrics` 表，用于长期趋势分析与 Dashboard：

```sql
CREATE TABLE monitoring_metrics (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    metric_name VARCHAR(64) NOT NULL,
    labels JSON,
    value DOUBLE,
    recorded_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_name_time (metric_name, recorded_at)
);
```

按 1 分钟批量聚合写入，避免每次请求写库。关键业务事件（拒答、fallback、任务失败）同步写入 `chat_events` / `index_task_events` 表。

---

## 4. 告警规则与阈值

按 P0/P1/P2 分级，建议基于 Prometheus Alertmanager 或同类方案配置。

| 优先级 | 告警名 | 规则 | 响应动作 |
|---|---|---|---|
| **P0** | `RAGLLMTimeoutHigh` | 过去 5 分钟 `rag_error_total{code="LLM_TIMEOUT"}` / 总请求 > 5% | 立即切换 LLM provider；通知 on-call |
| **P0** | `RAGRetrievalFailureSpike` | 过去 2 分钟 `rag_error_total{code="RETRIEVAL_ERROR"}` > 10 | 检查 Milvus/Redis 状态；启用 BM25 降级 |
| **P0** | `RAGIndexTaskFailed` | 任意重建任务 `task` 状态为 `failed` | 通知管理员；暂停自动上传索引 |
| **P1** | `RAGRefusalRateHigh` | 过去 1 小时拒答率 > 30% | 检查召回质量、阈值设置、知识库覆盖 |
| **P1** | `RAGRerankFallbackHigh` | 过去 1 小时 `is_fallback=true` 占比 > 20% | 检查重排服务/本地 vLLM；审查 RRF 分数质量 |
| **P1** | `RAGLatencyP95High` | 检索 P95 > 2000ms 或生成 P95 > 8000ms | 扩容/优化批大小/调整超时 |
| **P2** | `RAGModelHealthDegraded` | 模型可用性探测连续 3 次失败 | 标记 provider 为不健康；自动切换备用 |
| **P2** | `RAGStaleAnswerRateHigh` | 过去 24h `is_stale=true` > 15% | 提示管理员更新知识库文档 |

---

## 5. Fallback 策略

### 5.1 模型不可用 → 切换 Provider

当前 `Settings` 已区分 `llm_provider` / `reranker_provider`，但代码中未实现运行时切换。

实现方案：

- 在 `ModelClient` 内维护 provider 列表：`primary=dashscope`，`secondary=local`（或反之）。
- 调用失败且重试耗尽后，尝试 `secondary` provider；成功后记录 `model_provider_switched` 日志。
- 健康检查端点 `/health/models` 分别探测 embed / rerank / llm 可用性，供切换决策使用。

### 5.2 Reranker 失败 → 回退到 RRF 分数

该逻辑已在 `app/stages/reranking.py` 实现，需补充：

- 记录 `rerank_api_unavailable_falling_back` 指标到 Prometheus。
- 在 `RetrievalPipelineOutput` 中保留 `is_fallback=true`，使 `GenerationPipeline` 在阈值判断时跳过 rerank 分数尺度差异。
- 增加本地 reranker 与 DashScope 的双路探测，失败后再回退。

### 5.3 无召回 → 硬分支拒答

已在 `GenerationPipeline` 中实现。补充：

- 无召回时区分「无活跃索引」（`RuntimeError: No active index found`）与「有索引但无相关结果」。
- 前者返回明确引导：「请先重建索引」；后者返回现有拒答文案。
- 记录 `rag_refusal_total{reason="no_recall"}`。

### 5.4 Milvus 失败 → 降级到 BM25 或全局搜索

当前 `RetrievalPipeline` 中若 `MilvusStore` 异常会直接抛出。新增降级路径：

```python
try:
    vector_results = vector_stage.execute(...)
except MilvusUnavailableError:
    logger.warning("milvus_degraded_to_bm25_only", ...)
    vector_results = []
    # 标记本次为降级检索
    degraded = True
```

- 第一步降级：仅使用 BM25 召回。
- 第二步降级：BM25 也失败时，返回空结果并触发硬分支拒答。
- 若启用 LangChain 适配器，可额外尝试基于内存/缓存的全局关键词搜索。

### 5.5 LLM 超时 → 简短响应 / 道歉

当前 `ModelClient.chat()` 在超时后抛出异常，`ChatService.ask_stream()` 会 yield `error` 事件。

改进：

- 非流式请求：捕获 `httpx.TimeoutException` 后返回固定道歉文案，并标记 `is_timeout=true`。
- 流式请求：在已开始流后超时，立即发送终止 chunk：「抱歉，当前响应生成超时，请稍后重试。」
- 记录 `rag_error_total{code="LLM_TIMEOUT"}`，触发 P0 告警。

---

## 6. 重试与超时规范

| 操作 | 重试次数 | 退避策略 | 超时 | 备注 |
|---|---|---|---|---|
| Embedding | 3 | 指数退避 1s~10s | 30s | 批量大小 ≤ 10；按 provider 分别计数 |
| LLM 非流式 | 3 | 指数退避 1s~10s | 30s | 仅网络/连接/超时错误重试 |
| LLM 流式首 token | 2 | 固定 2s | 30s | 首 token 超时视为服务不可用 |
| Reranker | 2 | 指数退避 1s~5s | 15s | 失败后回退 RRF，不继续重试 |
| Milvus 查询 | 2 | 固定 1s | 10s | 失败后降级 BM25 |
| BM25 查询 | 1 | 无 | 5s | 本地文件操作，避免长时间阻塞 |
| GraphRAG 子图查询 | 1 | 无 | 5s（默认） | 失败仅记录日志，不影响主流程 |
| 索引原子切换锁 | 0 | 无 | 300s 阻塞等待 | 锁超时则任务失败 |

---

## 7. 日志、Tracing 与错误码规范

### 7.1 日志规范

沿用现有 `structlog` JSON 输出，新增强制字段：

- `request_id`：已存在，全链路透传。
- `trace_id` / `span_id`：引入 OpenTelemetry 后补充。
- `error_code`：见下表。
- `component`：如 `retrieval`、`generation`、`model_client`、`indexing`。
- `kb_id`、`conversation_id`：问答链路中尽量携带。

日志级别约定：

- `INFO`：正常完成、用户可感知的业务事件（如 `chat_answer_generated`）。
- `WARNING`：已降级但用户请求仍成功（如 rerank fallback、Milvus 降级）。
- `ERROR`：用户请求失败或索引任务失败。
- `CRITICAL`：服务级故障（如无法连接 Redis/MySQL）。

### 7.2 Tracing 规范

- 每个 `/chat` 请求作为一个 Trace。
- Span 划分：`query_rewrite`、`retrieval`、`rerank`、`graph_rag`、`generation`、`persistence`。
- 在 `ModelClient` 中为每个模型调用创建子 Span，记录 `model`、`provider`、`token_usage`、`latency_ms`。
- `request_id` 写入 HTTP Response Header，便于前后端对齐。

### 7.3 错误码规范

统一后端返回的错误结构：

```json
{
  "error": {
    "code": "MILVUS_UNAVAILABLE",
    "message": "向量检索服务暂不可用，已降级使用关键词检索",
    "detail": {"fallback": "bm25"}
  }
}
```

建议错误码列表：

| 错误码 | 含义 | HTTP 状态码 | 处理建议 |
|---|---|---|---|
| `INTERNAL_ERROR` | 未归类内部错误 | 500 | 已存在，保留 |
| `LLM_TIMEOUT` | 大模型响应超时 | 504 | 返回道歉文案 |
| `LLM_UNAVAILABLE` | 大模型服务不可用 | 503 | 切换 provider |
| `MILVUS_UNAVAILABLE` | 向量库不可用 | 503 | 降级 BM25 |
| `BM25_UNAVAILABLE` | 稀疏索引不可用 | 503 | 返回拒答 |
| `RERANKER_FALLBACK` | 重排服务降级 | 200 | 业务成功，仅标记 |
| `NO_ACTIVE_INDEX` | 未找到活跃索引 | 400 | 引导重建索引 |
| `REFUSAL` | 硬分支拒答 | 200 | 业务成功，标记 `is_refusal` |
| `INDEX_TASK_FAILED` | 索引任务失败 | 500 | 通知管理员 |
| `RATE_LIMITED` | 模型限流 | 429 | 指数退避重试 |

---

## 8. 实施步骤与验收标准

### 阶段一：指标埋点与暴露（1~2 天）

1. 在 `backend/app/metrics.py` 定义 Prometheus Registry 与核心指标。
2. 在 `ModelClient` 补充 `provider`、`model` 标签与错误码。
3. 在 `RetrievalPipeline`、`GenerationPipeline`、`ChatService` 补充 latency / recall / refusal / fallback 指标。
4. 新增 `/metrics` 路由与 `/health/models` 健康探测。
5. 在 MySQL 创建 `monitoring_metrics` 表，并写入聚合任务。

**验收标准**：

- 访问 `/metrics` 能看到 `rag_retrieval_latency_ms`、`rag_refusal_rate`、`rag_model_up` 等指标。
- 完成一次问答后，Grafana/日志中可查询到该次请求的 latency、recall_count、is_fallback、is_refusal。

### 阶段二：Fallback 补齐（2~3 天）

1. 实现 `ModelClient` 多 provider 自动切换。
2. 在 `RetrievalPipeline` 中捕获 `MilvusUnavailableError`，降级到 BM25-only。
3. 在 `GenerationPipeline` 中捕获 LLM 超时，返回道歉/简短响应。
4. 统一错误码与响应结构，更新 `generic_exception_handler`。
5. 在 `RerankingStage` 补充 fallback 指标埋点。

**验收标准**：

- 手动关闭 Milvus 后，问答仍能返回 BM25 召回结果，并标记 `is_fallback=true`。
- 手动让 LLM 超时后，用户收到「响应生成超时」提示，且 `rag_error_total{code="LLM_TIMEOUT"}` 计数增加。
- 切换 `llm_provider` 配置后，模型调用能自动路由到备用 provider。

### 阶段三：告警与 Dashboard（1~2 天）

1. 提供 `infra/prometheus.yml` 与 `infra/alert_rules.yml` 示例。
2. 在 Docker Compose 中加入 Prometheus + Grafana 可选 profile。
3. 在管理后台 `/admin/dashboard` 增加「系统健康」卡片：模型可用性、近 1h 拒答率、平均延迟、索引任务成功率。
4. 配置 Alertmanager webhook，推送到企业微信/飞书/邮件（示例即可）。

**验收标准**：

- Prometheus 能抓取后端 `/metrics`。
- 触发人工异常后，Alertmanager 能在 1 分钟内发出告警。
- Dashboard 展示近 1 小时核心指标趋势。

### 阶段四：Tracing 接入（可选，2 天）

1. 接入 OpenTelemetry FastAPI instrumentation。
2. 为 `RetrievalPipeline`、`GenerationPipeline`、`ModelClient` 手动创建 Span。
3. 将 trace 导出到 Jaeger/Tempo，并在日志中输出 `trace_id`。

**验收标准**：

- 单次 `/chat` 请求在 Jaeger 中可见完整调用链。
- `request_id` 与 `trace_id` 一一对应，便于排障。

---

## 9. 风险与注意事项

1. **避免指标埋点拖慢主流程**：Prometheus Histogram 采样、DB 聚合写入均使用异步/后台任务。
2. **Fallback 不能无限降级**：Milvus → BM25 → 拒答，避免在双存储均失败时编造答案。
3. **Provider 切换需考虑成本与兼容性**：本地 provider 需提前确认模型名、API 格式与 DashScope 兼容。
4. **告警阈值需结合实际流量校准**：初期可采用较宽松阈值，根据一周数据调整。
5. **保持现有测试覆盖**：新增 fallback 路径后，补充 `tests/test_retrieval_fallback.py`、`tests/test_model_client_provider_switch.py` 等测试。
