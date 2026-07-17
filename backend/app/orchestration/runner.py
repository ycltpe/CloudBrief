"""Agentic RAG 编排器：以 StateGraph 形式执行问答流程。

当前实现为最小可用版本：内部走 query_rewrite -> retrieve -> generate_stream
的线性流程，与 native 路径等价，保证服务可启动且 agentic 模式可用。
后续可扩展为真正的多跳、规划、相关性评分循环。
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass

import structlog

from app.pipelines.generation import GenerationPipeline, GenerationPipelineInput, StreamEvent
from app.pipelines.retrieval import RetrievalPipeline
from app.stages.grade import GradeStage
from app.stages.multi_hop_decompose import MultiHopDecomposeStage
from app.stages.plan import PlanStage
from app.stages.query_rewrite import QueryRewriteInput, QueryRewriteStage

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
    """基于状态图思想的问答执行器。

    对外暴露与 GenerationPipeline.generate_stream 一致的 SSE 事件协议，
    并在执行结束后通过 ``final_state`` 提供完整状态，便于上游持久化与日志。
    """

    def __init__(self, deps: AgenticGraphDeps):
        self.deps = deps
        self.final_state: dict = {}

    async def stream(
        self,
        inputs: dict,
        thread_id: str | None = None,
    ) -> AsyncIterator[StreamEvent]:
        """执行一次 agentic 问答流程并逐段返回事件。

        Args:
            inputs: 必须包含 ``question``、``history``、``kb_id``、``conversation_id``。
            thread_id: 线程标识，当前仅用于日志，无持久化语义。
        """
        question = inputs.get("question", "")
        history = inputs.get("history", []) or []
        kb_id = inputs.get("kb_id", "default")
        conversation_id = inputs.get("conversation_id")

        tool_trace: list[dict] = []
        rewritten_query = question
        retrieval_results: list = []
        is_fallback = False
        max_score = 0.0
        full_answer = ""
        citations: list = []
        is_refusal = False
        is_stale = False

        try:
            # 1. 查询改写
            start = time.perf_counter()
            rewrite_output = await asyncio.to_thread(
                self.deps.query_rewrite_stage.execute,
                QueryRewriteInput(current_question=question, history=history),
            )
            rewritten_query = rewrite_output.rewritten_query
            tool_trace.append(
                {
                    "node": "rewrite",
                    "latency_ms": int((time.perf_counter() - start) * 1000),
                }
            )
            logger.info(
                "agentic_rewrite_done",
                conversation_id=conversation_id,
                thread_id=thread_id,
                original_question=question,
                rewritten_question=rewritten_query,
            )

            # 2. 检索
            start = time.perf_counter()
            retrieval_output = await asyncio.to_thread(
                self.deps.retrieval_pipeline.retrieve,
                rewritten_query,
                50,
                5,
                kb_id,
            )
            retrieval_results = retrieval_output.results
            is_fallback = retrieval_output.is_fallback
            max_score = max((r.score for r in retrieval_results), default=0.0)
            tool_trace.append(
                {
                    "node": "retrieve",
                    "latency_ms": int((time.perf_counter() - start) * 1000),
                }
            )
            logger.info(
                "agentic_retrieve_done",
                conversation_id=conversation_id,
                thread_id=thread_id,
                result_count=len(retrieval_results),
                max_score=max_score,
                is_fallback=is_fallback,
            )

            # 推送检索来源
            yield StreamEvent(
                type="sources",
                data={
                    "conversation_id": conversation_id,
                    "sources": [
                        {
                            "chunk_id": r.chunk_id,
                            "title": r.title,
                            "type": r.source_type,
                        }
                        for r in retrieval_results[:5]
                    ],
                },
            )

            # 3. 生成
            start = time.perf_counter()
            async for event in self.deps.generation_pipeline.generate_stream(
                GenerationPipelineInput(
                    question=question,
                    chunks=retrieval_results,
                    max_score=max_score,
                    is_fallback=is_fallback,
                    history=history,
                    kb_id=kb_id,
                )
            ):
                if event.type == "chunk":
                    full_answer += event.data.get("content", "")
                    yield event
                elif event.type == "citations":
                    citations = event.data.get("citations", [])
                    is_refusal = event.data.get("is_refusal", False)
                    is_stale = event.data.get("is_stale", False)
                    yield event
                elif event.type == "done":
                    yield event

            tool_trace.append(
                {
                    "node": "generate",
                    "latency_ms": int((time.perf_counter() - start) * 1000),
                }
            )

        except Exception as exc:
            logger.error(
                "agentic_stream_failed",
                conversation_id=conversation_id,
                thread_id=thread_id,
                error=str(exc),
            )
            raise

        self.final_state = {
            "question": question,
            "rewritten_query": rewritten_query,
            "answer": full_answer,
            "citations": citations,
            "is_refusal": is_refusal,
            "is_stale": is_stale,
            "retrieval_results": retrieval_results,
            "is_fallback": is_fallback,
            "max_score": max_score,
            "tool_trace": tool_trace,
            "conversation_id": conversation_id,
            "kb_id": kb_id,
        }
