"""LangGraph StateGraph 定义：改写 → 规划 → 检索/多跳 → 评分 → 生成/拒答。

编译函数 ``build_agentic_graph`` 返回可复用的 CompiledGraph 实例；
节点内部委托现有 Stage 执行，同步 Stage 以 ``asyncio.to_thread`` 包裹。
"""

from __future__ import annotations

import asyncio
import dataclasses
import time
from typing import Literal

import structlog
from langgraph.graph import END, START, StateGraph
from langgraph.types import StreamWriter, interrupt

from app.orchestration.state import AgentState
from app.pipelines.generation import GenerationPipeline, GenerationPipelineInput
from app.pipelines.retrieval import RetrievalPipeline
from app.services.settings_service import SettingsService
from app.stages.base import RetrievalResult
from app.stages.grade import GradeInput, GradeStage
from app.stages.multi_hop_decompose import (
    MultiHopDecomposeInput,
    MultiHopDecomposeStage,
)
from app.stages.plan import PlanInput, PlanStage
from app.stages.query_rewrite import QueryRewriteInput, QueryRewriteStage

logger = structlog.get_logger()

# 最大检索跳数（全局预算）
MAX_HOPS = 2
# 第二跳起 top_k 减半
TOP_K_INITIAL = 50
TOP_K_PER_HOP = 5


class AgentGraphNodes:
    """持有 Stage 依赖并提供图节点函数。"""

    def __init__(
        self,
        *,
        retrieval_pipeline: RetrievalPipeline,
        generation_pipeline: GenerationPipeline,
        query_rewrite_stage: QueryRewriteStage,
        grade_stage: GradeStage,
        plan_stage: PlanStage,
        multi_hop_decompose_stage: MultiHopDecomposeStage,
        settings_service: SettingsService,
    ):
        self.retrieval_pipeline = retrieval_pipeline
        self.generation_pipeline = generation_pipeline
        self.query_rewrite_stage = query_rewrite_stage
        self.grade_stage = grade_stage
        self.plan_stage = plan_stage
        self.multi_hop_decompose_stage = multi_hop_decompose_stage
        self.settings_service = settings_service

    # ------------------------------------------------------------------
    # 工具方法
    # ------------------------------------------------------------------
    def _trace(
        self,
        tool_trace: list[dict] | None,
        *,
        node: str,
        latency_ms: int,
        extra: dict | None = None,
    ) -> list[dict]:
        entry: dict = {"node": node, "latency_ms": latency_ms}
        if extra:
            entry.update(extra)
        if tool_trace is None:
            return [entry]
        return tool_trace + [entry]

    def _current_max_score(self, results: list[RetrievalResult]) -> float:
        return max((r.score for r in results), default=0.0)

    @staticmethod
    def _metadata_to_dict(metadata) -> dict | None:
        """安全地将 RetrievalCascadeMetadata 或 dict 转为字典；Mock 对象返回 None。"""
        if metadata is None:
            return None
        if dataclasses.is_dataclass(metadata) and not isinstance(metadata, type):
            return dataclasses.asdict(metadata)
        if isinstance(metadata, dict):
            return metadata
        return None

    # ------------------------------------------------------------------
    # 节点
    # ------------------------------------------------------------------
    async def rewrite_node(self, state: AgentState) -> dict:
        start = time.perf_counter()
        output = await asyncio.to_thread(
            self.query_rewrite_stage.execute,
            QueryRewriteInput(
                current_question=state["question"],
                history=state.get("history") or [],
                previous_query=state.get("rewritten_query"),
                hop_count=state.get("hop_count", 0),
            ),
        )
        latency_ms = int((time.perf_counter() - start) * 1000)
        return {
            "rewritten_query": output.rewritten_query,
            "hop_count": state.get("hop_count", 0) + 1,
            "tool_trace": self._trace(
                state.get("tool_trace"),
                node="rewrite",
                latency_ms=latency_ms,
            ),
        }

    async def plan_node(self, state: AgentState) -> dict:
        start = time.perf_counter()
        output = await asyncio.to_thread(
            self.plan_stage.execute,
            PlanInput(
                question=state["rewritten_query"],
                history=state.get("history") or [],
            ),
        )
        latency_ms = int((time.perf_counter() - start) * 1000)

        # 当前 PlanStage 返回 steps；将单步视为 direct，多步视为 multi_hop
        route: Literal["direct", "multi_hop", "graph"] = "direct"
        if len(output.steps) > 1:
            route = "multi_hop"
        elif output.steps and output.steps[0].strip().lower().startswith("graph:"):
            route = "graph"

        return {
            "plan_route": route,
            "plan_reason": "基于步骤数路由",
            "tool_trace": self._trace(
                state.get("tool_trace"),
                node="plan",
                latency_ms=latency_ms,
                extra={"route": route},
            ),
        }

    async def retrieve_node(self, state: AgentState) -> dict:
        start = time.perf_counter()
        hop = state.get("hop_count", 0)
        top_k = TOP_K_INITIAL if hop == 0 else TOP_K_INITIAL // 2
        top_n = TOP_K_PER_HOP if hop == 0 else max(1, TOP_K_PER_HOP // 2)

        output = await asyncio.to_thread(
            self.retrieval_pipeline.retrieve,
            state["rewritten_query"],
            top_k,
            top_n,
            state.get("kb_id", "default"),
        )
        latency_ms = int((time.perf_counter() - start) * 1000)
        return {
            "retrieval_results": output.results,
            "is_fallback": output.is_fallback,
            "max_score": self._current_max_score(output.results),
            "retrieval_metadata": self._metadata_to_dict(output.retrieval_metadata),
            "tool_trace": self._trace(
                state.get("tool_trace"),
                node="retrieve",
                latency_ms=latency_ms,
                extra={"hop": hop, "result_count": len(output.results)},
            ),
        }

    async def grade_node(self, state: AgentState) -> dict:
        results = state.get("retrieval_results") or []
        if not results:
            return {
                "grade_passed": False,
                "grade_reason": "检索结果为空",
                "tool_trace": self._trace(
                    state.get("tool_trace"),
                    node="grade",
                    latency_ms=0,
                    extra={"passed": False, "reason": "empty_results"},
                ),
            }

        start = time.perf_counter()
        # 取 top-5 逐条评分，只要有任意一条相关即通过
        passed = False
        reason = "无相关片段"
        for chunk in results[:5]:
            grade = await asyncio.to_thread(
                self.grade_stage.execute,
                GradeInput(question=state["rewritten_query"], chunk=chunk),
            )
            if grade.is_relevant:
                passed = True
                reason = grade.reason or "找到相关片段"
                break

        latency_ms = int((time.perf_counter() - start) * 1000)
        return {
            "grade_passed": passed,
            "grade_reason": reason,
            "tool_trace": self._trace(
                state.get("tool_trace"),
                node="grade",
                latency_ms=latency_ms,
                extra={"passed": passed, "reason": reason},
            ),
        }

    async def multi_hop_decompose_node(self, state: AgentState) -> dict:
        start = time.perf_counter()
        output = await asyncio.to_thread(
            self.multi_hop_decompose_stage.execute,
            MultiHopDecomposeInput(
                question=state["rewritten_query"],
                history=state.get("history") or [],
            ),
        )
        latency_ms = int((time.perf_counter() - start) * 1000)
        return {
            "sub_questions": output.sub_questions,
            "tool_trace": self._trace(
                state.get("tool_trace"),
                node="multi_hop_decompose",
                latency_ms=latency_ms,
                extra={"sub_question_count": len(output.sub_questions)},
            ),
        }

    async def multi_hop_retrieve_node(self, state: AgentState) -> dict:
        sub_questions = state.get("sub_questions") or [state["rewritten_query"]]
        start = time.perf_counter()

        async def _retrieve_one(q: str) -> tuple[list[RetrievalResult], bool]:
            return await asyncio.to_thread(
                self.retrieval_pipeline.retrieve,
                q,
                TOP_K_INITIAL // 2,
                max(1, TOP_K_PER_HOP // 2),
                state.get("kb_id", "default"),
            )

        outputs = await asyncio.gather(*(_retrieve_one(q) for q in sub_questions))
        all_results: list[RetrievalResult] = []
        any_fallback = False
        aggregated_metadata: dict | None = None
        for output in outputs:
            all_results.extend(output.results)
            any_fallback = any_fallback or output.is_fallback
            meta_dict = self._metadata_to_dict(output.retrieval_metadata)
            if meta_dict:
                if aggregated_metadata is None:
                    aggregated_metadata = meta_dict
                else:
                    aggregated_metadata["vector_hits"] += meta_dict.get("vector_hits", 0)
                    aggregated_metadata["bm25_hits"] += meta_dict.get("bm25_hits", 0)
                    if meta_dict.get("rerank_provider", "").endswith(":fallback"):
                        aggregated_metadata["rerank_provider"] = meta_dict["rerank_provider"]

        # 按分数降序去重
        seen = set()
        unique_results: list[RetrievalResult] = []
        for r in sorted(all_results, key=lambda x: x.score, reverse=True):
            if r.chunk_id not in seen:
                seen.add(r.chunk_id)
                unique_results.append(r)

        latency_ms = int((time.perf_counter() - start) * 1000)
        return {
            "retrieval_results": unique_results,
            "is_fallback": any_fallback,
            "max_score": self._current_max_score(unique_results),
            "retrieval_metadata": aggregated_metadata,
            "tool_trace": self._trace(
                state.get("tool_trace"),
                node="multi_hop_retrieve",
                latency_ms=latency_ms,
                extra={"sub_question_count": len(sub_questions), "result_count": len(unique_results)},
            ),
        }

    async def generate_node(self, state: AgentState, writer: StreamWriter) -> dict:
        start = time.perf_counter()
        results = state.get("retrieval_results") or []
        max_score = state.get("max_score") or self._current_max_score(results)
        is_fallback = state.get("is_fallback", False)

        # 先推送检索来源，与 native 路径一致
        writer(
            {
                "type": "sources",
                "data": {
                    "conversation_id": state.get("conversation_id"),
                    "sources": [
                        {
                            "chunk_id": r.chunk_id,
                            "title": r.title,
                            "type": r.source_type,
                        }
                        for r in results[:5]
                    ],
                },
            }
        )

        full_answer = ""
        citations: list[dict] = []
        is_refusal = False
        is_stale = False

        async for event in self.generation_pipeline.generate_stream(
            GenerationPipelineInput(
                question=state["question"],
                chunks=results,
                max_score=max_score,
                is_fallback=is_fallback,
                history=state.get("history") or [],
                kb_id=state.get("kb_id"),
            )
        ):
            if event.type == "chunk":
                full_answer += event.data.get("content", "")
                writer(
                    {
                        "type": "chunk",
                        "data": {
                            "conversation_id": state.get("conversation_id"),
                            "content": event.data.get("content", ""),
                        },
                    }
                )
            elif event.type == "citations":
                citations = event.data.get("citations", [])
                is_refusal = event.data.get("is_refusal", False)
                is_stale = event.data.get("is_stale", False)
                # citations 事件在 runner 外层统一 yield，避免重复
            elif event.type == "status":
                writer({"type": "status", "data": event.data})

        latency_ms = int((time.perf_counter() - start) * 1000)
        return {
            "answer": full_answer,
            "citations": [c.model_dump() if hasattr(c, "model_dump") else c for c in citations],
            "is_refusal": is_refusal,
            "is_stale": is_stale,
            "tool_trace": self._trace(
                state.get("tool_trace"),
                node="generate",
                latency_ms=latency_ms,
                extra={"answer_length": len(full_answer)},
            ),
        }

    async def refusal_node(self, state: AgentState, writer: StreamWriter) -> dict:
        from app.pipelines.generation import RefusalResponse

        refusal = RefusalResponse()
        for line in refusal.answer.split("\n"):
            writer(
                {
                    "type": "chunk",
                    "data": {
                        "conversation_id": state.get("conversation_id"),
                        "content": line + "\n",
                    },
                }
            )
        writer(
            {
                "type": "citations",
                "data": {
                    "conversation_id": state.get("conversation_id"),
                    "citations": [],
                    "is_refusal": True,
                    "is_stale": False,
                    "diagnostics": {"refusal_reason": "low_retrieval_score_or_empty"},
                    "tokens_used": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
                },
            }
        )
        return {
            "answer": refusal.answer,
            "citations": [],
            "is_refusal": True,
            "is_stale": False,
            "tool_trace": self._trace(
                state.get("tool_trace"),
                node="refusal",
                latency_ms=0,
                extra={"reason": "low_retrieval_score_or_empty"},
            ),
        }

    # ------------------------------------------------------------------
    # 条件边
    # ------------------------------------------------------------------
    def plan_router(self, state: AgentState) -> Literal["retrieve", "multi_hop_decompose"]:
        route = state.get("plan_route", "direct")
        if route == "multi_hop":
            return "multi_hop_decompose"
        return "retrieve"

    def grade_router(
        self, state: AgentState,
    ) -> Literal["generate", "rewrite", "refusal"]:
        if state.get("grade_passed"):
            return "generate"
        if state.get("hop_count", 0) < MAX_HOPS - 1:
            return "rewrite"
        return "refusal"

    def multi_hop_interrupt_guard(
        self, state: AgentState,
    ) -> Literal["multi_hop_interrupt", "multi_hop_retrieve"]:
        if self.settings_service.get_runtime_value("agentic_interrupt_enabled"):
            return "multi_hop_interrupt"
        return "multi_hop_retrieve"


# ----------------------------------------------------------------------
# 中断节点（在 build_agentic_graph 外部定义，便于测试替换）
# ----------------------------------------------------------------------
def make_multi_hop_interrupt_node():
    async def _multi_hop_interrupt_node(state: AgentState) -> dict:
        value = interrupt(
            {
                "message": "多跳分解完成，等待人工确认是否继续检索",
                "sub_questions": state.get("sub_questions") or [],
                "snapshot": {
                    "question": state.get("question"),
                    "rewritten_query": state.get("rewritten_query"),
                    "plan_route": state.get("plan_route"),
                },
            }
        )
        return {
            "resume_payload": value if isinstance(value, dict) else {"resume": bool(value)},
        }

    return _multi_hop_interrupt_node


def build_agentic_graph(nodes: AgentGraphNodes) -> StateGraph:
    """构建并返回 Agentic 问答 StateGraph（未编译）。"""
    builder = StateGraph(AgentState)

    builder.add_node("rewrite", nodes.rewrite_node)
    builder.add_node("plan", nodes.plan_node)
    builder.add_node("retrieve", nodes.retrieve_node)
    builder.add_node("grade", nodes.grade_node)
    builder.add_node("multi_hop_decompose", nodes.multi_hop_decompose_node)
    builder.add_node("multi_hop_retrieve", nodes.multi_hop_retrieve_node)
    builder.add_node("generate", nodes.generate_node)
    builder.add_node("refusal", nodes.refusal_node)
    builder.add_node("multi_hop_interrupt", make_multi_hop_interrupt_node())

    builder.add_edge(START, "rewrite")
    builder.add_edge("rewrite", "plan")
    builder.add_conditional_edges("plan", nodes.plan_router)
    builder.add_edge("retrieve", "grade")
    builder.add_conditional_edges("grade", nodes.grade_router)

    # 多跳分支：分解后根据开关决定是否中断
    builder.add_conditional_edges(
        "multi_hop_decompose",
        nodes.multi_hop_interrupt_guard,
    )
    builder.add_edge("multi_hop_interrupt", "multi_hop_retrieve")
    builder.add_edge("multi_hop_retrieve", "grade")

    builder.add_edge("generate", END)
    builder.add_edge("refusal", END)

    return builder


# 模块级单例缓存（按 nodes 实例维度不做缓存，避免共享可变状态）
_compiled_graphs: dict[int, object] = {}


def compile_agentic_graph(nodes: AgentGraphNodes) -> object:
    """编译图为 CompiledGraph；相同 nodes 实例返回缓存结果。"""
    graph_id = id(nodes)
    if graph_id not in _compiled_graphs:
        _compiled_graphs[graph_id] = build_agentic_graph(nodes).compile()
    return _compiled_graphs[graph_id]
