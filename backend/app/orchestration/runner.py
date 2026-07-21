"""Agentic RAG 编排器：LangGraph StateGraph 执行与 SSE 事件映射。

对外暴露与 ``GenerationPipeline.generate_stream`` 一致的 SSE 事件协议，
并在执行结束后通过 ``final_state`` 提供完整状态，便于上游持久化与日志。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import structlog
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from app.orchestration.checkpointer import close_checkpointer, get_checkpointer
from app.orchestration.graph import AgentGraphNodes, build_agentic_graph
from app.orchestration.state import AgentState
from app.pipelines.generation import GenerationPipeline, StreamEvent
from app.pipelines.retrieval import RetrievalPipeline
from app.services.settings_service import SettingsService
from app.stages.grade import GradeStage
from app.stages.multi_hop_decompose import MultiHopDecomposeStage
from app.stages.plan import PlanStage
from app.stages.query_rewrite import QueryRewriteStage

logger = structlog.get_logger()


@dataclass
class AgenticGraphDeps:
    """AgentGraphRunner 运行所需的依赖集合。"""

    retrieval_pipeline: RetrievalPipeline
    generation_pipeline: GenerationPipeline
    query_rewrite_stage: QueryRewriteStage
    grade_stage: GradeStage
    plan_stage: PlanStage
    multi_hop_decompose_stage: MultiHopDecomposeStage


class AgentGraphRunner:
    """基于 LangGraph StateGraph 的问答执行器。

    - ``stream``：首次执行，可能因中断点而暂停。
    - ``resume``：在中断后恢复执行。
    - ``final_state``：执行/恢复结束后提供完整图状态。
    - ``interrupted`` / ``interrupt_value``：供上游判断当前是否处于中断等待。
    """

    def __init__(
        self,
        deps: AgenticGraphDeps,
        *,
        checkpointer: Any | None = None,
        settings_service: SettingsService | None = None,
    ):
        self.deps = deps
        self.settings_service = settings_service or SettingsService()
        self.nodes = AgentGraphNodes(
            retrieval_pipeline=deps.retrieval_pipeline,
            generation_pipeline=deps.generation_pipeline,
            query_rewrite_stage=deps.query_rewrite_stage,
            grade_stage=deps.grade_stage,
            plan_stage=deps.plan_stage,
            multi_hop_decompose_stage=deps.multi_hop_decompose_stage,
            settings_service=self.settings_service,
        )
        # 未传入 checkpointer 时使用 InMemorySaver（测试场景）；生产环境通过 create() 注入 SQLite
        self.checkpointer = checkpointer or InMemorySaver()
        self.graph = build_agentic_graph(self.nodes).compile(checkpointer=self.checkpointer)
        self.final_state: dict = {}
        self.interrupted = False
        self.interrupt_value: dict | None = None

    @classmethod
    async def create(
        cls,
        deps: AgenticGraphDeps,
        *,
        settings_service: SettingsService | None = None,
        sqlite_path: str | None = None,
        redis_url: str | None = None,
    ) -> AgentGraphRunner:
        """异步工厂：根据运行期 ``checkpoint_backend`` 创建对应 checkpointer 的 runner。"""
        svc = settings_service or SettingsService()
        checkpointer = await get_checkpointer(
            settings_service=svc,
            sqlite_path=sqlite_path,
            redis_url=redis_url,
        )
        return cls(deps, checkpointer=checkpointer, settings_service=svc)

    async def close(self) -> None:
        """关闭 checkpointer 持有的数据库/Redis 连接。"""
        await close_checkpointer(self.checkpointer)

    @staticmethod
    def _initial_state(inputs: dict) -> AgentState:
        return AgentState(
            question=inputs.get("question", ""),
            history=inputs.get("history") or [],
            kb_id=inputs.get("kb_id", "default"),
            conversation_id=inputs.get("conversation_id", ""),
            rewritten_query=inputs.get("question", ""),
            plan_route=None,
            plan_reason="",
            sub_questions=[],
            retrieval_results=[],
            is_fallback=False,
            max_score=0.0,
            grade_passed=False,
            grade_reason="",
            hop_count=0,
            answer="",
            citations=[],
            is_refusal=False,
            is_stale=False,
            tool_trace=[],
            interrupt_value=None,
            resume_payload=None,
        )

    def _config(self, thread_id: str | None) -> dict:
        return {"configurable": {"thread_id": thread_id or "default"}}

    async def _run_stream(
        self,
        input_value: AgentState | Command,
        thread_id: str | None,
    ) -> AsyncIterator[StreamEvent]:
        """通用执行循环：处理 LangGraph 事件并映射为 SSE StreamEvent。"""
        self.interrupted = False
        self.interrupt_value = None
        state_updates: dict[str, Any] = {}

        try:
            async for stream_mode, payload in self.graph.astream(
                input_value,
                self._config(thread_id),
                stream_mode=["updates", "custom"],
            ):
                if stream_mode == "custom":
                    event_type = payload.get("type")
                    event_data = payload.get("data", {})
                    if event_type in {"chunk", "status", "sources"}:
                        yield StreamEvent(type=event_type, data=event_data)
                    continue

                if stream_mode == "updates":
                    # 累积节点输出以得到近似最终状态
                    for node_output in payload.values():
                        if isinstance(node_output, dict):
                            state_updates.update(node_output)

                    # 检测 LangGraph 中断事件
                    if "__interrupt__" in payload:
                        interrupts = payload["__interrupt__"]
                        if interrupts:
                            self.interrupted = True
                            self.interrupt_value = interrupts[0].value
                            yield StreamEvent(
                                type="status",
                                data={
                                    "step": "interrupted",
                                    "message": "编排已暂停，等待人工确认",
                                    "interrupt": self.interrupt_value,
                                },
                            )
                        continue

            # 执行结束：尝试从 checkpointer 读取最终状态
            try:
                final = await self.graph.aget_state(self._config(thread_id))
                if final and final.values:
                    self.final_state = dict(final.values)
                else:
                    self.final_state = {**state_updates}
            except Exception as exc:
                logger.warning(
                    "agentic_final_state_read_failed",
                    thread_id=thread_id,
                    error=str(exc),
                )
                self.final_state = {**state_updates}

        except Exception as exc:
            logger.error(
                "agentic_stream_failed",
                thread_id=thread_id,
                error=str(exc),
            )
            raise

    async def stream(
        self,
        inputs: dict,
        thread_id: str | None = None,
    ) -> AsyncIterator[StreamEvent]:
        """执行一次 agentic 问答流程并逐段返回事件。

        Args:
            inputs: 必须包含 ``question``、``history``、``kb_id``、``conversation_id``。
            thread_id: 线程标识，等于 ``conversation_id``，用于 checkpointer 持久化。
        """
        initial_state = self._initial_state(inputs)
        async for event in self._run_stream(initial_state, thread_id):
            yield event

        # 正常结束（未中断）时补充 citations + done 事件，与 native 路径对齐
        if not self.interrupted:
            yield StreamEvent(
                type="citations",
                data={
                    "conversation_id": self.final_state.get("conversation_id"),
                    "citations": self.final_state.get("citations", []),
                    "is_refusal": self.final_state.get("is_refusal", False),
                    "is_stale": self.final_state.get("is_stale", False),
                },
            )
            yield StreamEvent(
                type="done",
                data={"conversation_id": self.final_state.get("conversation_id")},
            )

    async def resume(
        self,
        thread_id: str,
        resume_payload: dict | None = None,
    ) -> AsyncIterator[StreamEvent]:
        """从 checkpointer 恢复被中断的图执行。"""
        command = Command(resume=resume_payload if resume_payload is not None else True)
        async for event in self._run_stream(command, thread_id):
            yield event

        # 恢复完成后再 yield citations + done
        if not self.interrupted:
            yield StreamEvent(
                type="citations",
                data={
                    "conversation_id": self.final_state.get("conversation_id"),
                    "citations": self.final_state.get("citations", []),
                    "is_refusal": self.final_state.get("is_refusal", False),
                    "is_stale": self.final_state.get("is_stale", False),
                },
            )
            yield StreamEvent(
                type="done",
                data={"conversation_id": self.final_state.get("conversation_id")},
            )

    async def get_state(self, thread_id: str) -> dict:
        """获取指定线程的当前图状态快照。"""
        final = await self.graph.aget_state(self._config(thread_id))
        return dict(final.values) if final and final.values else {}
