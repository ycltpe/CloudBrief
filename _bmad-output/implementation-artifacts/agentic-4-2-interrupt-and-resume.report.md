---
story_id: 4.2
story_key: agentic-4-2-interrupt-and-resume
epic: 4
epic_title: 编排状态持久化与中断恢复
dependencies:
  - agentic-4-1-checkpointer-sqlite
status: done
implemented: 2026-07-17
---

# Story 4.2 实现报告：中断点与恢复执行

## 完成内容

### 1. LangGraph 编排基座重构（Story 4.1 同步补齐）

由于当前 `AgentGraphRunner` 仍为线性 Python 实现，无法直接接入 checkpointer 与中断恢复，本次将 `app/orchestration/` 重构为真正的 LangGraph StateGraph：

- `app/orchestration/state.py`
  - 定义 `AgentState` TypedDict，复用现有 `RetrievalResult` Pydantic 契约。
  - `tool_trace` 使用 `Annotated` + reducer 累加，其余字段按节点输出覆盖。
- `app/orchestration/graph.py`
  - 节点：rewrite / plan / retrieve / grade / multi_hop_decompose / multi_hop_retrieve / generate / refusal。
  - 条件边：plan 路由（direct/multi_hop）、grade 路由（generate/rewrite/refusal，max_hops=2 硬终止）。
  - 多跳分支默认走 `multi_hop_retrieve`；开启中断开关后进入 `multi_hop_interrupt` 节点调用 `interrupt()`。
- `app/orchestration/checkpointer.py`
  - 使用 `langgraph-checkpoint-sqlite` 的 `AsyncSqliteSaver`（异步版本）。
  - 提供 `get_checkpointer_async()` 工厂，路径从 `checkpoint_sqlite_path` 读取。
- `app/orchestration/runner.py`
  - `AgentGraphRunner.create()` 异步工厂注入 SQLite checkpointer。
  - `stream()` / `resume()` / `get_state()` 对外接口。
  - `stream_mode=["updates","custom"]` 事件映射为 SSE `chunk/status/sources`；正常结束时统一 yield `citations` + `done`。

### 2. 中断点开关（Story 4.2 核心）

- 注册运行期配置 `agentic_interrupt_enabled`（默认 `false`，分组「适配器」）。
  - `app/config.py` 添加字段。
  - `app/services/settings_service.py` 注册 `SettingMeta`。
  - `.env.example` 添加 `AGENTIC_INTERRUPT_ENABLED=false`。
- 当开关为 `true` 且 plan 节点路由到 `multi_hop` 时，图在 `multi_hop_decompose` 后进入 `multi_hop_interrupt` 节点，调用 `interrupt()` 暂停。
- 中断时 `runner.interrupted=True`，`runner.interrupt_value` 包含子问题列表与状态快照；SSE 向前端发送 `status: interrupted` 事件。

### 3. 状态快照查看与恢复 API

- `GET /chat/{conversation_id}/agentic-state`
  - 返回当前 conversation 的图状态快照与是否处于中断等待。
- `POST /chat/{conversation_id}/agentic-resume`
  - 接收任意 JSON payload（默认 `{}`），通过 `Command(resume=payload)` 恢复图执行。
  - 以 SSE 形式继续输出后续事件，最终结果与不中断执行一致。
- `ChatService` 新增：
  - `get_agentic_state(conversation_id)`
  - `resume_agentic_stream(conversation_id, resume_payload)`

### 4. 测试

新增 `backend/tests/test_orchestration_graph.py`，覆盖：

- direct 路径事件输出（sources/chunk/citations/done）。
- 低分检索触发改写重试，第二次仍低分走拒答。
- 空检索直接走拒答。
- 开启中断时多跳分解后暂停，恢复后继续执行得到答案。
- 关闭中断时多跳路径直接走完。
- 状态契约复用 `RetrievalResult`。
- `tool_trace` 各节点被记录。

## 验证结果

```bash
cd backend
uv run ruff check .      # All checks passed
uv run pytest -q         # 103 passed, 1 warning
```

## 关键文件变更

- 新增
  - `backend/app/orchestration/state.py`
  - `backend/app/orchestration/graph.py`
  - `backend/app/orchestration/checkpointer.py`
  - `backend/tests/test_orchestration_graph.py`
- 修改
  - `backend/app/orchestration/runner.py`（重构为 LangGraph）
  - `backend/app/orchestration/__init__.py`
  - `backend/app/services/chat_service.py`（中断/恢复方法 + runner 创建方式）
  - `backend/app/api/chat.py`（新增两个端点）
  - `backend/app/config.py`
  - `backend/app/services/settings_service.py`
  - `.env.example`
  - `_bmad-output/implementation-artifacts/sprint-status.yaml`

## 后续工作

- Story 4.3：评估并决定是否迁移至 `langgraph-checkpoint-redis`（复用现有 Redis 6381）。
