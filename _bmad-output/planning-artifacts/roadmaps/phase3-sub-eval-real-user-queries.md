# Phase 3 子方案：真实用户查询抽样评估

## 1. 评估目标与指标

### 1.1 目标

在真实用户查询流量中建立可持续的抽样评估机制，量化 CloudBrief 支持副驾在检索、生成、引用、拒答、时效等关键环节的质量，支撑 A/B 实验、bad case 复盘与产品迭代决策。

### 1.2 指标体系

| 维度 | 指标 | 定义 | 当前可复用组件 |
|---|---|---|---|
| 检索准确率 | `context_precision@N` | Top-N 检索片段中被 LLM judge 判定为相关的比例 | `backend/eval/metrics.py` |
| 检索召回率 | `context_recall@N` | 问题所需关键知识点在 Top-N 片段中的覆盖比例（无标准答案时由 LLM judge 估计） | `backend/eval/metrics.py` |
| 引用正确性 | `citation_precision` | 答案中引用的 chunk 确实支持对应论断的比例 | `CitationParser` + LLM judge |
| 引用正确性 | `citation_recall` | 答案中应有引用支持的论断实际被引用的比例 | LLM judge |
| 拒答合理性 | `false_refusal_rate` | 知识库可回答但被错误拒答的比例 | `GenerationPipeline` 拒答分支 |
| 拒答合理性 | `false_accept_rate` | 知识库不可回答但系统未拒答的比例 | LLM judge |
| 生成质量 | `faithfulness` | 答案中可由检索片段直接支撑的论断比例 | `backend/eval/metrics.py` |
| 生成质量 | `answer_relevance` | 答案对问题的相关程度 | `backend/eval/metrics.py` |
| 生成质量 | `completeness` | 答案覆盖问题所有关键点的程度 | LLM judge |
| 时效性 | `stale_rate` | 命中超期 chunk（`is_stale=true`）的查询占比 | `GenerationPipeline._check_staleness` |
| 延迟 | `latency_total_p50/p90/p99` | 端到端耗时（改写 → 检索 → 生成） | `ModelClient` 日志 + 阶段计时 |
| 延迟 | `latency_stage_ms` | 各阶段耗时分布 | 新增阶段计时 |
| 用户满意度 | `human_score` / `thumbs_up_rate` | 人工 1-5 分评分或点赞率 | `EvalResult.human_score` |

## 2. 抽样策略

### 2.1 样本量

| 场景 | 建议样本量 | 说明 |
|---|---|---|
| 每周质量基线 | 100 条/周 | 在 95% 置信水平、±10% 误差范围内估计主要比例指标 |
| 人工深度标注 | 50 条/周 | 由 QA/产品共同标注，覆盖主要分层 |
| A/B 实验 | 每组 ≥200 条 | 按 5% 最小可检测差异（MDE）估算 |
| Bad case 复盘 | 20 条/场 | 取当周低分、高延迟、异常拒答样本 |

### 2.2 抽样周期

- **实时入池**：每次对话完成后异步写入 `query_logs`。
- **周度采样**：每周一 02:00 通过 Celery beat 任务执行一次分层抽样，生成当周 `eval_results` 待标注批次。
- **A/B 实验**：实验期间每日采样，实验结束后汇总。

### 2.3 分层方法

按以下维度分层后随机抽样，避免长尾查询被淹没：

1. **问题类型**：`help_doc`、`faq`、`changelog`、`ticket`、`out_of_scope`（由轻量级分类器或关键词规则初分）。
2. **答案形态**：正常回答、`is_refusal=true`、`is_stale=true`、`graphrag_enabled=true`。
3. **用户角色**：`admin`、`qa`、`user`。
4. **知识库目录**：按 `kb_id` 分层，确保各业务线覆盖。
5. **检索状态**：`is_fallback=true`（reranker 失效回退）单独成层。

抽样 SQL 示例：

```sql
SELECT * FROM (
  SELECT *, ROW_NUMBER() OVER (
    PARTITION BY question_type, answer_shape
    ORDER BY RAND()
  ) AS rn
  FROM query_logs
  WHERE created_at >= DATE_SUB(NOW(), INTERVAL 7 DAY)
) t
WHERE rn <= 10;
```

### 2.4 匿名化与隐私合规

- `user_id`、`conversation_id` 采用加盐 SHA-256 单向哈希后存储，原始 ID 仅保留 7 天用于客服追溯。
- 问题文本通过正则脱敏：手机号、邮箱、身份证号、工号、客户名。
- 仅保留与评估相关的字段，移除未使用的 Cookie、IP、设备指纹。
- 访问控制：`/admin/eval/*` 仅对 `admin`/`qa` 开放（已由 `require_role` 保护）。

## 3. 标注流程

### 3.1 自动标注 vs 人工标注

| 阶段 | 方式 | 内容 |
|---|---|---|
| 自动标注 | LLM-as-judge | 对每个样本自动计算 `context_precision`、`faithfulness`、`answer_relevance` 等 |
| 人工标注 | QA/产品 | 对周度 50 条样本进行 1-5 分整体评分及多维度标注 |
| 冲突仲裁 | 专家组 | 对 IAA < 0.75 的维度重新讨论并修订标注规范 |

### 3.2 标注维度与打分标准

| 维度 | 分值 | 说明 |
|---|---|---|
| 检索相关性 | 1-5 | 检索到的片段是否包含回答问题所需信息 |
| 答案忠实度 | 1-5 | 答案是否严格基于检索片段，无事实幻觉 |
| 引用正确性 | 1-5 | 引用标记是否准确对应来源，无漏引、错引 |
| 拒答合理性 | 1-5 | 拒答是否符合“知识库未覆盖”原则 |
| 时效提示 | 1-5 | 对 `is_stale=true` 的回答是否恰当提示用户 |
| 整体满意度 | 1-5 | 若你是提问用户，对该回答的综合满意度 |

每个维度可附加二进制标签：

- `hallucination`：答案包含检索片段未支持的信息。
- `missing_citation`：应有引用却未引用。
- `wrong_refusal`：本可回答却被拒答。
- `stale_ignored`：引用了过期资料但未提示。

### 3.3 一致性校验

1. 校准集：抽取 30 条样本由 2 名标注员独立标注。
2. 计算 Cohen's Kappa，目标 ≥ 0.75。
3. 未达标时召开规范修订会，重新标注校准集。
4. 正式标注实行“双盲 + 仲裁”机制，争议样本由第三位标注员裁决。

## 4. 工具与方法

### 4.1 RAGAS / LLM-as-judge

- 复用 `backend/eval/metrics.py` 中的 `LLMJudgeMetrics`，基于 `ModelClient` 统一调用。
- 对真实查询扩展以下 prompt：

```text
你是一名严谨的 RAG 评测员。请根据问题、检索片段与系统回答，输出 JSON：
{
  "context_precision": 0.0~1.0,
  "context_recall": 0.0~1.0,
  "faithfulness": 0.0~1.0,
  "answer_relevance": 0.0~1.0,
  "citation_precision": 0.0~1.0,
  "citation_recall": 0.0~1.0,
  "should_refuse": true|false,
  "reason": "简要说明"
}
```

- 所有 judge 调用使用 `temperature=0.0`，输出通过 `_extract_json` 解析并做异常回退。

### 4.2 A/B 测试

- **分组**：按 `user_id` 哈希取模或随机 bucket，将用户划分到控制组与实验组。
- **可实验变量**：
  - `retrieval_adapter`：`native` vs `langchain`
  - `reranker_provider`：`dashscope` vs `local`
  - GraphRAG：`enabled` vs `shadow_mode` vs `disabled`
  - `refusal_threshold`：0.2 / 0.3 / 0.4
- **对比指标**：`faithfulness`、`answer_relevance`、`false_refusal_rate`、`latency_p90`。
- **统计方法**：采用 bootstrap 95% 置信区间；样本量不足时仅输出点估计与趋势。
- **影子模式**：复用 `chat_service.py` 中已有的 `shadow_mode`，在不改变用户体验的前提下并行生成 GraphRAG 答案并对比。

### 4.3 Bad Case 复盘会

- **频率**：双周一次，每次 30-60 分钟。
- **素材来源**：
  - 当周 `human_score ≤ 2` 的样本；
  - `faithfulness < 0.5` 的样本；
  - `latency_total_p99` 最高的 10 条；
  - 用户主动点踩或反馈“未解决”的样本。
- **输出**：每条 bad case 必须落到以下分类之一并关联 action owner：
  - 检索缺失 → 补充文档 / 调整分片
  - 引用错误 → 优化 `CitationParser`
  - 拒答不当 → 调整 `refusal_threshold`
  - 幻觉 → 优化 prompt / 加入事实校验
  - 性能 → 索引 / 模型 / 并发优化

## 5. 数据收集与存储

### 5.1 查询日志 Schema

新增 `query_logs` 表，记录每次问答的完整运行时上下文：

```sql
CREATE TABLE query_logs (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  log_hash CHAR(64) NOT NULL UNIQUE COMMENT 'conversation_id+question+created_at 加盐哈希',
  user_hash CHAR(64) COMMENT 'user_id 加盐哈希',
  received_at DATETIME NOT NULL INDEX,
  original_question TEXT NOT NULL,
  rewritten_question TEXT,
  kb_id VARCHAR(64),
  question_type VARCHAR(32) COMMENT 'help_doc/faq/changelog/ticket/out_of_scope',
  
  -- 运行时配置快照
  config_snapshot JSON COMMENT 'embedding_model/llm_model/reranker_provider/refusal_threshold等',
  
  -- 检索结果
  retrieval_adapter VARCHAR(32),
  is_fallback BOOLEAN DEFAULT FALSE,
  max_score FLOAT,
  retrieved_chunks JSON,
  
  -- 生成结果
  answer TEXT,
  citations_json JSON,
  is_refusal BOOLEAN DEFAULT FALSE,
  is_stale BOOLEAN DEFAULT FALSE,
  graphrag_enabled BOOLEAN DEFAULT FALSE,
  graphrag_used BOOLEAN DEFAULT FALSE,
  
  -- 延迟（毫秒）
  latency_ms_rewrite INT,
  latency_ms_retrieve INT,
  latency_ms_generate INT,
  latency_ms_total INT,
  
  -- 用户反馈
  user_feedback VARCHAR(16) COMMENT 'up/down/null',
  user_feedback_note TEXT,
  
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_received_at (received_at),
  INDEX idx_question_type (question_type),
  INDEX idx_is_refusal (is_refusal),
  INDEX idx_kb_id (kb_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

### 5.2 标注结果存储位置

- 自动/人工标注结果统一存入现有 `eval_results` 表（`backend/app/stores/db.py`）。
- `eval_results.reasoning_json` 扩展为包含 `query_log_id`、`sample_layer`、`judge_prompt_version`。
- 通过 `query_log_id` 与 `query_logs` 关联，支持从标注结果回溯到原始运行上下文。

### 5.3 现有组件复用

| 组件 | 用途 |
|---|---|
| `backend/app/services/chat_service.py` | 在 `ask` / `ask_stream` 中插入计时与日志写入 |
| `backend/app/pipelines/retrieval.py` | 输出检索结果与 `is_fallback` |
| `backend/app/pipelines/generation.py` | 输出答案、`is_refusal`、`is_stale`、citations |
| `backend/app/clients/model_client.py` | 统一提供 judge 调用入口 |
| `backend/app/stores/eval_results.py` | 持久化评测与人工反馈 |
| `backend/app/api/admin/eval.py` | 管理后台列表、反馈、导出 |
| `backend/eval/run_eval.py` | 批量评测脚本模板 |

### 5.4 日志写入方式

在 `ChatService` 的 `ask` / `ask_stream` 中，将持久化逻辑后的后台任务扩展为同时写入 `query_logs`：

```python
asyncio.create_task(
    asyncio.to_thread(
        self._log_query,
        conversation_id=conversation_id,
        user_id=user_id,
        request=request,
        rewritten_query=query,
        retrieval_output=retrieval_output,
        generation_output=generation_output,
        latency=latency,
    )
)
```

`_log_query` 负责：
1. 敏感信息脱敏。
2. 记录 `config_snapshot`（调用 `SettingsService` 读取运行时配置）。
3. 将延迟与结果写入 `query_logs`。
4. 异步触发自动 judge（可选，避免阻塞主响应）。

## 6. 实施步骤与验收标准

### 步骤 1：查询日志采集

- 新增 `query_logs` 表与 `QueryLogStore`。
- 在 `ChatService` 中加入阶段计时与日志写入。
- 每日校验数据完整性。

**验收标准**：100% 真实问答写入 `query_logs`；7 天内无 PII 泄露事件；`latency_ms_total` 与前端感知延迟误差 < 10%。

### 步骤 2：自动评估流水线

- 新增 `backend/eval/real_eval.py`，从 `query_logs` 采样并调用 `LLMJudgeMetrics`。
- 自动评分结果写入 `eval_results`。
- 支持按 `question_type`、`kb_id`、`config_snapshot` 分组汇总。

**验收标准**：每周一 08:00 前完成上周自动评估；关键指标缺失率 < 2%。

### 步骤 3：人工标注界面增强

- 在 `frontend/app/admin/eval` 页面增加：
  - 原始问题与改写后查询并列展示
  - 检索片段来源与得分
  - citation 高亮
  - 多维度打分表单
  - “采纳 / 需修改”标记
- 支持按 `has_feedback=false` 筛选未标注样本。

**验收标准**：QA 标注效率 ≥ 20 条/小时；双盲 Cohen's Kappa ≥ 0.75。

### 步骤 4：Dashboard 指标看板

- 在 `/admin/dashboard` 扩展：
  - 本周 `faithfulness` / `answer_relevance` 均值
  - `latency_total_p50/p90/p99`
  - 拒答率、过期率、用户满意度
  - A/B 实验分组对比（若有）

**验收标准**：Dashboard 每日刷新；核心指标与 `eval_results` 汇总一致。

### 步骤 5：A/B 测试与 Bad Case 复盘

- 在 `system_settings` 中新增 `ab_test_config` JSON 配置。
- 按用户 bucket 路由不同配置，并将 bucket 写入 `query_logs`。
- 双周运行 bad case 复盘会并产出 action items。

**验收标准**：能够在不停机情况下切换实验组配置；每次复盘输出 ≥ 5 条可追踪改进项。

## 7. 风险与缓解措施

| 风险 | 影响 | 缓解措施 |
|---|---|---|
| **LLM judge 成本与延迟** | 自动评估调用量大，费用高 | 仅对采样样本调用完整 judge；小模型或本地模型做预筛；设置 judge 超时与失败回退 |
| **隐私合规** | 真实查询可能含客户敏感信息 | 入池即脱敏；哈希化用户 ID；限制 QA 访问范围；定期审计 |
| **抽样偏差** | 高频简单问题占比过高，掩盖长尾问题 | 按问题类型、拒答/过期状态分层；主动对低分样本过采样 |
| **标注一致性差** | 人工评分标准不统一 | 校准集 + Cohen's Kappa；双盲仲裁；持续迭代标注规范 |
| **运行时性能开销** | 日志写入与 judge 调用拖慢响应 | 日志与 judge 均走后台任务；对 judge 调用限流；采样而非全量 judge |
| **A/B 实验混杂因素** | 用户 self-selection、知识库更新导致指标波动 | 固定实验周期；实验期间冻结知识库与阈值；使用 user-level bucket |
| **拒答阈值漂移** | `refusal_threshold` 调整导致 false_refusal_rate 突增 | 每次阈值变更同步记录到 `config_snapshot`；监控拒答率波动 |
| **模型/索引版本漂移** | 评估结果跨周不可比 | `query_logs` 强制保存配置快照；每周生成版本化报告 |
