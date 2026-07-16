import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal

import structlog
from pydantic import BaseModel

from app.clients.model_client import ModelClient
from app.config import get_settings
from app.metrics import ERROR_TOTAL, GENERATION_LATENCY, REFUSAL_RATE
from app.models.graph_schemas import SubgraphContext
from app.models.schemas import Citation
from app.services.settings_service import SettingsService
from app.stages.base import RetrievalResult
from app.stages.citation_parser import CitationParserInput, CitationParserStage
from app.stages.generation_llm import GenerationInput, GenerationLLMStage
from app.stages.graph_rag_context_stage import GraphRAGContextStage
from app.stores.graph_schema_store import GraphSchemaStore
from app.stores.graph_store import GraphStore

logger = structlog.get_logger()


class GenerationPipelineInput(BaseModel):
    question: str
    chunks: list[RetrievalResult]
    max_score: float
    is_fallback: bool = False
    history: list[dict] = []
    kb_id: str | None = None
    graph_context: SubgraphContext | None = None


class GenerationPipelineOutput(BaseModel):
    answer: str
    citations: list[Citation] = []
    is_refusal: bool = False
    is_stale: bool = False
    diagnostics: dict = {}


class RefusalResponse(BaseModel):
    is_refusal: bool = True
    answer: str = (
        "未在知识库中检索到与问题直接相关的内容。\n\n"
        "你可以尝试：\n"
        "1. 换几种关键词或更简短的问法重新提问；\n"
        "2. 检查是否已上传相关文档到知识库；\n"
        "3. 联系管理员补充最新资料。"
    )
    diagnostics: dict = {}


@dataclass
class StreamEvent:
    type: Literal["chunk", "citations", "status", "done", "error", "sources"]
    data: dict[str, Any]


class GenerationPipeline:
    """生成管线：硬分支拒答 -> LLM 生成 -> 引用解析 -> 时效检查。"""

    def __init__(self, model_client: ModelClient, graph_store: GraphStore | None = None):
        self.model_client = model_client
        self.graph_store = graph_store
        self.settings = get_settings()
        self.settings_service = SettingsService()
        self.llm_stage = GenerationLLMStage(model_client)
        self.citation_parser = CitationParserStage()

    async def _maybe_fetch_graph_context(
        self,
        question: str,
        kb_id: str | None,
    ) -> SubgraphContext | None:
        if not kb_id or not self.graph_store or not self.graph_store.is_available:
            return None
        try:
            schema_store = GraphSchemaStore()
            schema = await asyncio.to_thread(
                schema_store.get_by_directory_id, int(kb_id)
            )
            if not schema or not schema.enabled:
                return None
            if not (schema.entity_types or schema.relation_types):
                return None

            stage = GraphRAGContextStage(self.graph_store, model_client=self.model_client)
            timeout = getattr(self.settings, "graphrag_timeout_seconds", 5.0)
            context = await asyncio.wait_for(
                stage.run(question, kb_id, schema=schema),
                timeout=timeout,
            )
            if context and context.text:
                return context
        except Exception as exc:
            logger.warning("graph_rag_context_failed", kb_id=kb_id, error=str(exc))
        return None

    async def generate(self, input_data: GenerationPipelineInput) -> GenerationPipelineOutput:
        import time

        start = time.perf_counter()
        diagnostics = {
            "recall_count": len(input_data.chunks),
            "max_score": input_data.max_score,
        }

        # 硬分支拒答：rerank fallback 时跳过阈值检查，因为此时分数来自 RRF 与 rerank 不同尺度
        threshold = self.settings_service.get_runtime_value("refusal_threshold")
        should_refuse = (
            len(input_data.chunks) == 0
            or (not input_data.is_fallback and input_data.max_score < threshold)
        )
        if should_refuse:
            REFUSAL_RATE.labels(reason="no_recall", kb_id=input_data.kb_id or "default").inc()
            return GenerationPipelineOutput(
                answer=RefusalResponse().answer,
                is_refusal=True,
                diagnostics=diagnostics,
            )

        graph_context = input_data.graph_context
        if graph_context is None:
            graph_context = await self._maybe_fetch_graph_context(
                input_data.question,
                input_data.kb_id,
            )
        if graph_context and graph_context.diagnostics:
            diagnostics["graph_rag"] = graph_context.diagnostics

        try:
            llm_output = await self.llm_stage.execute(
                GenerationInput(
                    question=input_data.question,
                    chunks=input_data.chunks,
                    history=input_data.history,
                    graph_context=graph_context,
                )
            )
        except TimeoutError as exc:
            logger.warning("llm_generation_timeout", error=str(exc))
            ERROR_TOTAL.labels(code="LLM_TIMEOUT", component="generation").inc()
            return GenerationPipelineOutput(
                answer="抱歉，当前响应生成超时，请稍后重试。",
                is_refusal=False,
                diagnostics=diagnostics,
            )
        except Exception as exc:
            logger.error(
                "llm_generation_failed",
                error=str(exc),
                model=self.settings_service.get_runtime_value("llm_model"),
                provider=self.settings_service.get_runtime_value("llm_provider"),
            )
            ERROR_TOTAL.labels(code="LLM_UNAVAILABLE", component="generation").inc()
            return GenerationPipelineOutput(
                answer="抱歉，当前生成服务暂不可用，请稍后重试。",
                is_refusal=False,
                diagnostics=diagnostics,
            )
        finally:
            latency_ms = int((time.perf_counter() - start) * 1000)
            GENERATION_LATENCY.labels(
                provider=self.settings_service.get_runtime_value("llm_provider"),
                model=self.settings_service.get_runtime_value("llm_model"),
            ).observe(latency_ms)

        parsed = self.citation_parser.execute(
            CitationParserInput(raw_answer=llm_output.raw_answer, chunks=input_data.chunks)
        )

        is_stale = self._check_staleness(input_data.chunks)

        return GenerationPipelineOutput(
            answer=parsed.clean_answer,
            citations=parsed.citations,
            is_refusal=False,
            is_stale=is_stale,
            diagnostics=diagnostics,
        )

    async def generate_stream(self, input_data: GenerationPipelineInput) -> AsyncIterator[StreamEvent]:
        """流式生成：先 yield answer 增量，最后 yield citations + done 元事件。"""
        import time

        start = time.perf_counter()
        diagnostics = {
            "recall_count": len(input_data.chunks),
            "max_score": input_data.max_score,
        }
        logger.info(
            "generation_stream_start",
            kb_id=input_data.kb_id,
            recall_count=len(input_data.chunks),
            max_score=input_data.max_score,
            is_fallback=input_data.is_fallback,
        )

        # 硬分支拒答：rerank fallback 时跳过阈值检查，因为此时分数来自 RRF 与 rerank 不同尺度
        threshold = self.settings_service.get_runtime_value("refusal_threshold")
        should_refuse = (
            len(input_data.chunks) == 0
            or (not input_data.is_fallback and input_data.max_score < threshold)
        )
        if should_refuse:
            REFUSAL_RATE.labels(reason="no_recall", kb_id=input_data.kb_id or "default").inc()
            logger.info(
                "generation_stream_refuse",
                threshold=threshold,
                reason="no_recall_or_low_score",
                latency_ms=int((time.perf_counter() - start) * 1000),
            )
            refusal = RefusalResponse()
            yield StreamEvent(type="chunk", data={"content": refusal.answer})
            yield StreamEvent(
                type="citations",
                data={
                    "citations": [],
                    "is_refusal": True,
                    "is_stale": False,
                    "diagnostics": diagnostics,
                },
            )
            yield StreamEvent(type="done", data={})
            return

        graph_context = input_data.graph_context
        if graph_context is None:
            start_graph = time.perf_counter()
            graph_context = await self._maybe_fetch_graph_context(
                input_data.question,
                input_data.kb_id,
            )
            logger.info(
                "generation_stream_step_done",
                step="graph_rag",
                has_context=bool(graph_context and graph_context.text),
                latency_ms=int((time.perf_counter() - start_graph) * 1000),
            )
        if graph_context and graph_context.diagnostics:
            diagnostics["graph_rag"] = graph_context.diagnostics
            yield StreamEvent(
                type="status",
                data={"step": "graph_rag", "message": "已注入图谱上下文"},
            )

        raw_answer = ""
        chunk_count = 0
        first_chunk_latency_ms = None
        start_llm = time.perf_counter()
        logger.info("generation_stream_step_start", step="llm_stream")
        try:
            async for chunk in self.llm_stage.execute_stream(
                GenerationInput(
                    question=input_data.question,
                    chunks=input_data.chunks,
                    history=input_data.history,
                    graph_context=graph_context,
                )
            ):
                if first_chunk_latency_ms is None:
                    first_chunk_latency_ms = int((time.perf_counter() - start_llm) * 1000)
                    logger.info(
                        "generation_stream_first_chunk",
                        first_chunk_latency_ms=first_chunk_latency_ms,
                    )
                raw_answer += chunk
                chunk_count += 1
                yield StreamEvent(type="chunk", data={"content": chunk})
            logger.info(
                "generation_stream_step_done",
                step="llm_stream",
                chunk_count=chunk_count,
                first_chunk_latency_ms=first_chunk_latency_ms,
                answer_length=len(raw_answer),
                latency_ms=int((time.perf_counter() - start_llm) * 1000),
            )
        except TimeoutError as exc:
            logger.warning("llm_stream_timeout", error=str(exc))
            ERROR_TOTAL.labels(code="LLM_TIMEOUT", component="generation").inc()
            yield StreamEvent(
                type="chunk",
                data={"content": "抱歉，当前响应生成超时，请稍后重试。"},
            )
            yield StreamEvent(
                type="citations",
                data={"citations": [], "is_refusal": False, "is_stale": False, "diagnostics": diagnostics},
            )
            yield StreamEvent(type="done", data={})
            return
        except Exception as exc:
            logger.error(
                "llm_stream_failed",
                error=str(exc),
                model=self.settings_service.get_runtime_value("llm_model"),
                provider=self.settings_service.get_runtime_value("llm_provider"),
            )
            ERROR_TOTAL.labels(code="LLM_UNAVAILABLE", component="generation").inc()
            yield StreamEvent(
                type="chunk",
                data={"content": "抱歉，当前生成服务暂不可用，请稍后重试。"},
            )
            yield StreamEvent(
                type="citations",
                data={"citations": [], "is_refusal": False, "is_stale": False, "diagnostics": diagnostics},
            )
            yield StreamEvent(type="done", data={})
            return
        finally:
            latency_ms = int((time.perf_counter() - start) * 1000)
            GENERATION_LATENCY.labels(
                provider=self.settings_service.get_runtime_value("llm_provider"),
                model=self.settings_service.get_runtime_value("llm_model"),
            ).observe(latency_ms)

        start_parse = time.perf_counter()
        parsed = self.citation_parser.execute(
            CitationParserInput(raw_answer=raw_answer, chunks=input_data.chunks)
        )
        is_stale = self._check_staleness(input_data.chunks)
        logger.info(
            "generation_stream_step_done",
            step="citation_parse",
            citation_count=len(parsed.citations),
            is_stale=is_stale,
            latency_ms=int((time.perf_counter() - start_parse) * 1000),
        )

        yield StreamEvent(
            type="citations",
            data={
                "citations": [c.model_dump() for c in parsed.citations],
                "is_refusal": False,
                "is_stale": is_stale,
                "diagnostics": diagnostics,
            },
        )
        yield StreamEvent(type="done", data={})
        logger.info(
            "generation_stream_done",
            total_latency_ms=int((time.perf_counter() - start) * 1000),
            chunk_count=chunk_count,
            answer_length=len(raw_answer),
        )

    def _check_staleness(self, chunks: list[RetrievalResult]) -> bool:
        threshold = timedelta(days=self.settings_service.get_runtime_value("stale_threshold_days"))
        now = datetime.utcnow()
        for chunk in chunks:
            updated_at = chunk.updated_at
            if isinstance(updated_at, str):
                try:
                    updated_at = datetime.fromisoformat(updated_at)
                except ValueError:
                    continue
            if isinstance(updated_at, datetime) and (now - updated_at) > threshold:
                return True
        return False
