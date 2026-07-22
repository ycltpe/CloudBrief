import asyncio
import dataclasses
import json
import re
import time
from collections import Counter
from collections.abc import AsyncIterator
from datetime import datetime

import structlog

from app.clients.model_client import ModelClient
from app.config import get_settings
from app.models.schemas import (
    ChatRequest,
    ChatResponse,
    Citation,
    ConversationSummary,
    UserOut,
)
from app.orchestration import AgentGraphRunner, AgenticGraphDeps
from app.pipelines.generation import (
    GenerationPipeline,
    GenerationPipelineInput,
    StreamEvent,
)
from app.pipelines.retrieval import RetrievalPipeline
from app.services.settings_service import SettingsService
from app.stages.grade import GradeStage
from app.stages.graph_rag_context_stage import GraphRAGContextStage
from app.stages.multi_hop_decompose import MultiHopDecomposeStage
from app.stages.plan import PlanStage
from app.stages.query_rewrite import QueryRewriteInput, QueryRewriteStage
from app.stages.self_querying import SelfQueryingInput, SelfQueryingStage
from app.stores.conversation import ConversationStore
from app.stores.graph_schema_store import GraphSchemaStore
from app.stores.graph_shadow_store import GraphShadowStore
from app.stores.graph_store import GraphStore
from app.stores.kb_access import KbAccessStore
from app.stores.query_log import QueryLogStore

logger = structlog.get_logger()


class ChatService:
    """聊天流程编排：会话 -> 查询改写 -> 检索 -> 生成 -> 持久化。"""

    def __init__(self, graph_store: GraphStore | None = None):
        self.settings = get_settings()
        self.conversation_store = ConversationStore()
        self.model_client = ModelClient(self.settings)
        self.retrieval_pipeline = RetrievalPipeline(self.model_client)
        self.generation_pipeline = GenerationPipeline(self.model_client, graph_store=graph_store)
        self.graph_store = graph_store
        self.graph_schema_store = GraphSchemaStore()
        self.query_rewrite_stage = QueryRewriteStage()
        self.self_querying_stage = SelfQueryingStage(self.model_client)
        self.grade_stage = GradeStage(self.model_client)
        self.plan_stage = PlanStage(self.model_client, self.graph_schema_store)
        self.multi_hop_decompose_stage = MultiHopDecomposeStage(self.model_client)
        self.graph_shadow_store = GraphShadowStore()
        self.plan_stage = PlanStage(self.model_client, self.graph_schema_store)
        self.multi_hop_decompose_stage = MultiHopDecomposeStage(self.model_client)
        self.graph_shadow_store = GraphShadowStore()
        self.kb_access_store = KbAccessStore()
        self.settings_service = SettingsService()
        self.query_log_store = QueryLogStore()

    async def _fetch_graph_context(self, question: str, kb_id: str | None):
        if not kb_id or not self.graph_store or not self.graph_store.is_available:
            return None
        try:
            schema = await asyncio.to_thread(
                self.graph_schema_store.get_by_directory_id, int(kb_id)
            )
            if not schema or not schema.enabled:
                return None
            if not (schema.entity_types or schema.relation_types):
                return None
            stage = GraphRAGContextStage(self.graph_store, model_client=self.model_client)
            timeout = self.settings_service.get_runtime_value("graphrag_timeout_seconds")
            return await asyncio.wait_for(
                stage.run(question, kb_id, schema=schema),
                timeout=timeout,
            )
        except Exception as exc:
            logger.warning("chat_fetch_graph_context_failed", kb_id=kb_id, error=str(exc))
        return None

    async def _is_shadow_mode_enabled(self, kb_id: str | None) -> bool:
        if not kb_id:
            return False
        try:
            schema = await asyncio.to_thread(
                self.graph_schema_store.get_by_directory_id, int(kb_id)
            )
            return bool(schema and schema.shadow_mode)
        except Exception:
            return False

    @staticmethod
    def _derive_kb_id(chunks: list) -> str | None:
        """从检索结果 source_id 中推导所属知识库目录 ID。"""
        pattern = re.compile(r"^kb/dir_(\d+)/")
        matches = [m.group(1) for c in chunks for m in [pattern.match(c.source_id)] if m]
        if not matches:
            return None
        return Counter(matches).most_common(1)[0][0]

    async def _resolve_kb_id(self, request: ChatRequest, current_user: UserOut | None) -> str:
        """根据请求中的 kb_ids 与当前用户权限解析本次查询使用的知识库 id。

        2 周 MVP 仅支持单库查询；admin 可访问全部，普通用户仅能访问已授权库。
        """
        kb_ids = request.kb_ids or []
        is_admin = current_user is not None and current_user.role == "admin"

        if not kb_ids:
            # 未指定时：admin 使用 default；普通用户使用其有权限的唯一库或 default
            if is_admin:
                return "default"
            accessible = await asyncio.to_thread(
                self.kb_access_store.get_user_accessible_kb_ids,
                current_user.id if current_user else 0,
                include_default=True,
            )
            return accessible[0] if len(accessible) == 1 else "default"

        selected = kb_ids[0]
        if len(kb_ids) > 1:
            logger.warning("multi_kb_not_supported_in_mvp", kb_ids=kb_ids, selected=selected)

        if selected == "default" or is_admin:
            return selected

        if current_user:
            has_access = await asyncio.to_thread(
                self.kb_access_store.check_access, selected, current_user.id
            )
            if has_access:
                return selected

        raise PermissionError(f"用户无权访问知识库 {selected}")

    async def ask(
        self,
        request: ChatRequest,
        current_user: UserOut | None = None,
    ) -> ChatResponse:
        user_id = current_user.id if current_user else None
        received_at = datetime.utcnow()
        start_total = time.perf_counter()
        conversation_id = request.conversation_id
        if not conversation_id:
            conversation_id = await asyncio.to_thread(
                self.conversation_store.create,
                user_id=user_id,
            )
        kb_id = await self._resolve_kb_id(request, current_user)

        # 读取历史并改写查询
        start_rewrite = time.perf_counter()
        history = await asyncio.to_thread(self.get_history, conversation_id)
        rewrite_output = await asyncio.to_thread(
            self.query_rewrite_stage.execute,
            QueryRewriteInput(
                current_question=request.question,
                history=history,
            ),
        )
        query = rewrite_output.rewritten_query
        latency_ms_rewrite = int((time.perf_counter() - start_rewrite) * 1000)

        # Self-Querying：把问题中的时间/来源类型约束翻译为 Milvus filter
        sq_dropped_fields: list[str] = []
        applied_filter: str | None = None
        if self.settings_service.get_runtime_value("self_querying_enabled"):
            sq_output = await self.self_querying_stage.execute(
                SelfQueryingInput(question=query)
            )
            query = sq_output.query
            applied_filter = sq_output.filter
            sq_dropped_fields = sq_output.dropped_fields

        # 检索
        start_retrieve = time.perf_counter()
        retrieval_output = await asyncio.to_thread(
            self.retrieval_pipeline.retrieve, query, 50, 5, kb_id, applied_filter
        )
        retrieval_results = retrieval_output.results
        is_fallback = retrieval_output.is_fallback
        latency_ms_retrieve = int((time.perf_counter() - start_retrieve) * 1000)

        # 生成
        start_generate = time.perf_counter()
        generation_output = await self.generation_pipeline.generate(
            GenerationPipelineInput(
                question=request.question,
                chunks=retrieval_results,
                max_score=max((r.score for r in retrieval_results), default=0.0),
                is_fallback=is_fallback,
                history=history,
                kb_id=kb_id,
            )
        )
        latency_ms_generate = int((time.perf_counter() - start_generate) * 1000)
        latency_ms_total = int((time.perf_counter() - start_total) * 1000)

        # Shadow mode：在不影响最终答案的前提下记录 GraphRAG 候选答案
        graphrag_enabled = bool(kb_id and await self._is_shadow_mode_enabled(kb_id))
        graphrag_used = False
        if kb_id and await self._is_shadow_mode_enabled(kb_id):
            try:
                graph_context = await self._fetch_graph_context(request.question, kb_id)
                graph_output = await self.generation_pipeline.generate(
                    GenerationPipelineInput(
                        question=request.question,
                        chunks=retrieval_results,
                        max_score=max((r.score for r in retrieval_results), default=0.0),
                        is_fallback=is_fallback,
                        history=history,
                        kb_id=kb_id,
                        graph_context=graph_context,
                    )
                )
                import json
                await asyncio.to_thread(
                    self.graph_shadow_store.record,
                    kb_id=kb_id,
                    user_id=user_id,
                    question=request.question,
                    vector_answer=generation_output.answer,
                    graph_answer=graph_output.answer,
                    subgraph_context_json=json.dumps(graph_context.diagnostics if graph_context else {}, ensure_ascii=False),
                )
                graphrag_used = bool(graph_context)
            except Exception as exc:
                logger.warning("shadow_mode_record_failed", kb_id=kb_id, error=str(exc))

        # 保存消息
        await asyncio.to_thread(
            self.conversation_store.append_message,
            conversation_id=conversation_id,
            role="user",
            content=request.question,
        )

        # 首次提问时初始化标题；旧数据无 user_id 时补录
        conversation = await asyncio.to_thread(
            self.conversation_store.get_conversation, conversation_id
        )
        if conversation:
            if user_id is not None and conversation.user_id is None:
                await asyncio.to_thread(
                    self.conversation_store.update_user_id, conversation_id, user_id
                )
            if not conversation.title:
                default_title = request.question[:16]
                await asyncio.to_thread(
                    self.conversation_store.update_title, conversation_id, default_title
                )

        await asyncio.to_thread(
            self.conversation_store.append_message,
            conversation_id=conversation_id,
            role="assistant",
            content=generation_output.answer,
            citations=generation_output.citations,
            is_refusal=generation_output.is_refusal,
        )
        await asyncio.to_thread(
            self.conversation_store.update_timestamp, conversation_id
        )

        logger.info(
            "chat_answer_generated",
            conversation_id=conversation_id,
            user_id=user_id,
            is_refusal=generation_output.is_refusal,
            is_stale=generation_output.is_stale,
        )

        # 异步写入查询日志
        retrieval_metadata = (
            dataclasses.asdict(retrieval_output.retrieval_metadata)
            if retrieval_output.retrieval_metadata
            else None
        )
        asyncio.create_task(
            asyncio.to_thread(
                self._log_query,
                user_id=user_id,
                received_at=received_at,
                original_question=request.question,
                rewritten_question=query,
                kb_id=kb_id,
                retrieval_adapter=self.settings_service.get_runtime_value("retrieval_adapter"),
                is_fallback=is_fallback,
                max_score=max((r.score for r in retrieval_results), default=0.0) if retrieval_results else None,
                retrieval_results=retrieval_results,
                answer=generation_output.answer,
                citations=generation_output.citations,
                is_refusal=generation_output.is_refusal,
                is_stale=generation_output.is_stale,
                graphrag_enabled=graphrag_enabled,
                graphrag_used=graphrag_used,
                latency_ms_rewrite=latency_ms_rewrite,
                latency_ms_retrieve=latency_ms_retrieve,
                latency_ms_generate=latency_ms_generate,
                latency_ms_total=latency_ms_total,
                self_querying_dropped_fields=sq_dropped_fields,
                retrieval_metadata=retrieval_metadata,
            )
        )

        return ChatResponse(
            conversation_id=conversation_id,
            answer=generation_output.answer,
            citations=generation_output.citations,
            is_refusal=generation_output.is_refusal,
            is_stale=generation_output.is_stale,
            kb_id=kb_id,
        )

    async def ask_stream(
        self,
        request: ChatRequest,
        current_user: UserOut | None = None,
    ) -> AsyncIterator[StreamEvent]:
        """按 orchestration_mode 分发编排路径。

        agentic 走 StateGraph 编排；native / langchain 走既有线性流程
        （langchain 档的检索差异由 retrieval_adapter 在管线内细分）。
        """
        mode = self.settings_service.get_runtime_value("orchestration_mode")
        if mode == "agentic":
            async for event in self._ask_stream_agentic(request, current_user=current_user):
                yield event
            return
        async for event in self._ask_stream_native(request, current_user=current_user):
            yield event

    async def _ask_stream_native(
        self,
        request: ChatRequest,
        current_user: UserOut | None = None,
    ) -> AsyncIterator[StreamEvent]:
        """流式问答：实时 yield 增量文本与最终引用/元数据。"""
        user_id = current_user.id if current_user else None
        received_at = datetime.utcnow()
        start_total = time.perf_counter()
        full_answer = ""
        conversation_id = None
        citations = []
        is_refusal = False
        is_stale = False
        query = ""
        kb_id = "default"
        retrieval_results = []
        is_fallback = False
        latency_ms_rewrite = None
        latency_ms_retrieve = None
        latency_ms_generate = None
        sq_dropped_fields: list[str] = []
        applied_filter: str | None = None

        try:
            # 立刻让前端感知到“已收到”，避免长时间空白
            yield StreamEvent(
                type="status",
                data={"step": "received", "message": "已收到，我先查一下知识库…"},
            )
            logger.info("chat_stream_step_start", step="received", conversation_id=conversation_id)

            # 会话创建、历史读取、查询改写都是同步/IO 操作，放到线程池避免阻塞事件循环
            start_rewrite = time.perf_counter()
            conversation_id = request.conversation_id or await asyncio.to_thread(
                self.conversation_store.create,
                user_id=user_id,
            )
            logger.info(
                "chat_stream_step_done",
                step="create_conversation",
                conversation_id=conversation_id,
                latency_ms=int((time.perf_counter() - start_rewrite) * 1000),
            )

            history = await asyncio.to_thread(self.get_history, conversation_id)
            logger.info(
                "chat_stream_step_done",
                step="load_history",
                conversation_id=conversation_id,
                message_count=len(history),
                latency_ms=int((time.perf_counter() - start_rewrite) * 1000),
            )

            rewrite_output = await asyncio.to_thread(
                self.query_rewrite_stage.execute,
                QueryRewriteInput(
                    current_question=request.question,
                    history=history,
                ),
            )
            query = rewrite_output.rewritten_query
            logger.info(
                "chat_stream_step_done",
                step="query_rewrite",
                conversation_id=conversation_id,
                original_question=request.question,
                rewritten_question=query,
                latency_ms=int((time.perf_counter() - start_rewrite) * 1000),
            )

            kb_id = await self._resolve_kb_id(request, current_user)
            latency_ms_rewrite = int((time.perf_counter() - start_rewrite) * 1000)

            # Self-Querying：把问题中的时间/来源类型约束翻译为 Milvus filter
            if self.settings_service.get_runtime_value("self_querying_enabled"):
                sq_output = await self.self_querying_stage.execute(
                    SelfQueryingInput(question=query)
                )
                query = sq_output.query
                applied_filter = sq_output.filter
                sq_dropped_fields = sq_output.dropped_fields

            logger.info(
                "chat_stream_step_done",
                step="resolve_kb",
                conversation_id=conversation_id,
                kb_id=kb_id,
                latency_ms=latency_ms_rewrite,
            )

            yield StreamEvent(
                type="status",
                data={"step": "retrieving", "message": "正在检索相关知识库…"},
            )
            logger.info("chat_stream_step_start", step="retrieving", conversation_id=conversation_id)

            # 检索阶段也放到线程池，避免阻塞 ASGI 事件循环
            start_retrieve = time.perf_counter()
            retrieval_output = await asyncio.to_thread(
                self.retrieval_pipeline.retrieve, query, 50, 5, kb_id, applied_filter
            )
            retrieval_results = retrieval_output.results
            is_fallback = retrieval_output.is_fallback
            source_count = len(retrieval_results)
            latency_ms_retrieve = int((time.perf_counter() - start_retrieve) * 1000)
            logger.info(
                "chat_stream_step_done",
                step="retrieve",
                conversation_id=conversation_id,
                kb_id=kb_id,
                result_count=source_count,
                is_fallback=is_fallback,
                max_score=max((r.score for r in retrieval_results), default=0.0),
                latency_ms=latency_ms_retrieve,
            )

            # 先把检索到的来源标题推给前端， citations 不必等到生成结束
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
            logger.info(
                "chat_stream_step_done",
                step="yield_sources",
                conversation_id=conversation_id,
                source_count=min(source_count, 5),
            )

            if source_count > 0:
                generating_message = f"找到 {source_count} 条相关资料，正在组织回答…"
            else:
                generating_message = "未找到直接相关资料，正在基于现有知识组织回答…"

            yield StreamEvent(
                type="status",
                data={"step": "generating", "message": generating_message},
            )
            logger.info(
                "chat_stream_step_start",
                step="generating",
                conversation_id=conversation_id,
                message=generating_message,
            )

            # 流式生成
            start_generate = time.perf_counter()
            chunk_count = 0
            async for event in self.generation_pipeline.generate_stream(
                GenerationPipelineInput(
                    question=request.question,
                    chunks=retrieval_results,
                    max_score=max((r.score for r in retrieval_results), default=0.0),
                    is_fallback=is_fallback,
                    history=history,
                    kb_id=kb_id,
                )
            ):
                if event.type == "chunk":
                    chunk_count += 1
                    full_answer += event.data.get("content", "")
                    yield StreamEvent(
                        type="chunk",
                        data={
                            "conversation_id": conversation_id,
                            "content": event.data.get("content", ""),
                        },
                    )
                elif event.type == "citations":
                    citations = event.data.get("citations", [])
                    is_refusal = event.data.get("is_refusal", False)
                    is_stale = event.data.get("is_stale", False)
                    yield StreamEvent(
                        type="citations",
                        data={
                            "conversation_id": conversation_id,
                            "citations": citations,
                            "is_refusal": is_refusal,
                            "is_stale": is_stale,
                        },
                    )
                    logger.info(
                        "chat_stream_step_done",
                        step="citations",
                        conversation_id=conversation_id,
                        citation_count=len(citations),
                        is_refusal=is_refusal,
                        is_stale=is_stale,
                    )
                elif event.type == "done":
                    yield StreamEvent(
                        type="done",
                        data={"conversation_id": conversation_id},
                    )
            latency_ms_generate = int((time.perf_counter() - start_generate) * 1000)
            latency_ms_total = int((time.perf_counter() - start_total) * 1000)
            logger.info(
                "chat_stream_step_done",
                step="generate_stream",
                conversation_id=conversation_id,
                chunk_count=chunk_count,
                answer_length=len(full_answer),
                latency_ms=latency_ms_generate,
            )

            # 持久化移到后台任务，避免拖尾阻塞响应收尾
            asyncio.create_task(
                asyncio.to_thread(
                    self._persist_chat,
                    conversation_id=conversation_id,
                    user_id=user_id,
                    question=request.question,
                    full_answer=full_answer,
                    citations=citations,
                    is_refusal=is_refusal,
                    is_stale=is_stale,
                )
            )
            logger.info(
                "chat_stream_step_start",
                step="persist_chat_background",
                conversation_id=conversation_id,
            )

            # Shadow mode：后台记录 GraphRAG 候选答案，不影响用户流
            graphrag_enabled = bool(kb_id and await self._is_shadow_mode_enabled(kb_id))
            graphrag_used = False
            if kb_id and await self._is_shadow_mode_enabled(kb_id):
                asyncio.create_task(
                    self._record_shadow_async(
                        kb_id=kb_id,
                        user_id=user_id,
                        question=request.question,
                        retrieval_results=retrieval_results,
                        is_fallback=is_fallback,
                        history=history,
                        vector_answer=full_answer,
                    )
                )
                # 简单判断：如果 shadow 记录成功则认为 graphrag_used 为 true
                graphrag_used = graphrag_enabled

            # 异步写入查询日志
            retrieval_metadata = (
                dataclasses.asdict(retrieval_output.retrieval_metadata)
                if retrieval_output.retrieval_metadata
                else None
            )
            asyncio.create_task(
                asyncio.to_thread(
                    self._log_query,
                    user_id=user_id,
                    received_at=received_at,
                    original_question=request.question,
                    rewritten_question=query,
                    kb_id=kb_id,
                    retrieval_adapter=self.settings_service.get_runtime_value("retrieval_adapter"),
                    is_fallback=is_fallback,
                    max_score=max((r.score for r in retrieval_results), default=0.0) if retrieval_results else None,
                    retrieval_results=retrieval_results,
                    answer=full_answer,
                    citations=citations,
                    is_refusal=is_refusal,
                    is_stale=is_stale,
                    graphrag_enabled=graphrag_enabled,
                    graphrag_used=graphrag_used,
                    latency_ms_rewrite=latency_ms_rewrite,
                    latency_ms_retrieve=latency_ms_retrieve,
                    latency_ms_generate=latency_ms_generate,
                    latency_ms_total=latency_ms_total,
                    self_querying_dropped_fields=sq_dropped_fields,
                    retrieval_metadata=retrieval_metadata,
                )
            )
        except Exception as exc:
            logger.error(
                "chat_stream_failed",
                conversation_id=conversation_id,
                user_id=user_id,
                error=str(exc),
            )
            yield StreamEvent(
                type="error",
                data={
                    "conversation_id": conversation_id,
                    "message": str(exc),
                },
            )

    async def _record_shadow_async(
        self,
        *,
        kb_id: str,
        user_id: int | None,
        question: str,
        retrieval_results: list,
        is_fallback: bool,
        history: list,
        vector_answer: str,
    ) -> None:
        try:
            graph_context = await self._fetch_graph_context(question, kb_id)
            graph_output = await self.generation_pipeline.generate(
                GenerationPipelineInput(
                    question=question,
                    chunks=retrieval_results,
                    max_score=max((r.score for r in retrieval_results), default=0.0),
                    is_fallback=is_fallback,
                    history=history,
                    kb_id=kb_id,
                    graph_context=graph_context,
                )
            )
            import json
            await asyncio.to_thread(
                self.graph_shadow_store.record,
                kb_id=kb_id,
                user_id=user_id,
                question=question,
                vector_answer=vector_answer,
                graph_answer=graph_output.answer,
                subgraph_context_json=json.dumps(
                    graph_context.diagnostics if graph_context else {}, ensure_ascii=False
                ),
            )
        except Exception as exc:
            logger.warning("shadow_mode_record_async_failed", kb_id=kb_id, error=str(exc))

    def get_history(self, conversation_id: str) -> list:
        messages = self.conversation_store.get_messages(conversation_id)
        result = []
        for msg in messages:
            entry: dict = {
                "role": msg.role,
                "content": msg.content,
                "is_refusal": msg.is_refusal,
                "created_at": msg.created_at.isoformat() if msg.created_at else None,
            }
            if msg.citations_json:
                try:
                    entry["citations"] = json.loads(msg.citations_json)
                except Exception:
                    entry["citations"] = []
            result.append(entry)
        return result

    def _persist_chat(
        self,
        *,
        conversation_id: str,
        user_id: int | None,
        question: str,
        full_answer: str,
        citations: list,
        is_refusal: bool,
        is_stale: bool,
    ) -> None:
        """在后台线程中持久化聊天消息，不阻塞 SSE 响应收尾。"""
        start = time.perf_counter()
        try:
            self.conversation_store.append_message(
                conversation_id=conversation_id,
                role="user",
                content=question,
            )
            conversation = self.conversation_store.get_conversation(conversation_id)
            if conversation:
                if user_id is not None and conversation.user_id is None:
                    self.conversation_store.update_user_id(conversation_id, user_id)
                if not conversation.title:
                    default_title = question[:16]
                    self.conversation_store.update_title(conversation_id, default_title)
            self.conversation_store.append_message(
                conversation_id=conversation_id,
                role="assistant",
                content=full_answer,
                citations=[Citation(**c) for c in citations],
                is_refusal=is_refusal,
            )
            self.conversation_store.update_timestamp(conversation_id)

            logger.info(
                "chat_answer_streamed",
                conversation_id=conversation_id,
                user_id=user_id,
                is_refusal=is_refusal,
                is_stale=is_stale,
                latency_ms=int((time.perf_counter() - start) * 1000),
            )
        except Exception as exc:
            logger.error(
                "chat_persist_failed",
                conversation_id=conversation_id,
                user_id=user_id,
                error=str(exc),
            )

    def list_conversations(
        self,
        user_id: int,
        limit: int = 100,
    ) -> list[ConversationSummary]:
        conversations = self.conversation_store.list_by_user(user_id, limit=limit)
        summaries: list[ConversationSummary] = []
        for conversation in conversations:
            last_msg = self.conversation_store.get_last_message(conversation.id)
            preview = ""
            if last_msg:
                preview = last_msg.content[:60]
            summaries.append(
                ConversationSummary(
                    id=conversation.id,
                    title=conversation.title,
                    preview=preview,
                    updated_at=conversation.updated_at.isoformat() if conversation.updated_at else None,
                )
            )
        return summaries

    def update_conversation_title(
        self,
        conversation_id: str,
        user_id: int,
        title: str,
    ) -> bool:
        conversation = self.conversation_store.get_conversation(conversation_id)
        if not conversation or conversation.user_id != user_id:
            return False
        return self.conversation_store.update_title(conversation_id, title)

    def _log_query(
        self,
        *,
        user_id: int | None,
        received_at: datetime,
        original_question: str,
        rewritten_question: str | None,
        kb_id: str,
        retrieval_adapter: str,
        is_fallback: bool,
        max_score: float | None,
        retrieval_results: list,
        answer: str | None,
        citations: list,
        is_refusal: bool,
        is_stale: bool,
        graphrag_enabled: bool,
        graphrag_used: bool,
        latency_ms_rewrite: int | None,
        latency_ms_retrieve: int | None,
        latency_ms_generate: int | None,
        latency_ms_total: int | None,
        tool_trace: list | None = None,
        self_querying_dropped_fields: list[str] | None = None,
        retrieval_metadata: dict | None = None,
    ) -> None:
        """在后台线程中写入 query_logs，不阻塞主响应。"""
        try:
            config_snapshot = {
                "embedding_model": self.settings_service.get_runtime_value("embedding_model"),
                "llm_model": self.settings_service.get_runtime_value("llm_model"),
                "orchestration_mode": self.settings_service.get_runtime_value("orchestration_mode"),
                "reranker_provider": self.settings_service.get_runtime_value("reranker_provider"),
                "refusal_threshold": self.settings_service.get_runtime_value("refusal_threshold"),
                "stale_threshold_days": self.settings_service.get_runtime_value("stale_threshold_days"),
                "self_querying_enabled": self.settings_service.get_runtime_value("self_querying_enabled"),
                "vector_index_type": self.settings_service.get_runtime_value("vector_index_type"),
                "shadow_index_type": self.settings_service.get_runtime_value("shadow_index_type"),
                "shadow_ratio": self.settings_service.get_runtime_value("shadow_ratio"),
            }
            self.query_log_store.insert(
                user_id=user_id,
                received_at=received_at,
                original_question=original_question,
                rewritten_question=rewritten_question,
                kb_id=kb_id,
                question_type=None,
                config_snapshot=config_snapshot,
                retrieval_adapter=retrieval_adapter,
                is_fallback=is_fallback,
                max_score=max_score,
                retrieved_chunks=retrieval_results,
                answer=answer,
                citations=citations,
                is_refusal=is_refusal,
                is_stale=is_stale,
                graphrag_enabled=graphrag_enabled,
                graphrag_used=graphrag_used,
                latency_ms_rewrite=latency_ms_rewrite,
                latency_ms_retrieve=latency_ms_retrieve,
                latency_ms_generate=latency_ms_generate,
                latency_ms_total=latency_ms_total,
                tool_trace=tool_trace,
                self_querying_dropped_fields=self_querying_dropped_fields,
                retrieval_metadata=retrieval_metadata,
            )
        except Exception as exc:
            logger.warning("query_log_insert_failed", user_id=user_id, error=str(exc))

    async def _ask_stream_agentic(
        self,
        request: ChatRequest,
        current_user: UserOut | None = None,
    ) -> AsyncIterator[StreamEvent]:
        """agentic 编排路径：StateGraph 执行与 native 等价的问答流程。

        会话创建、历史读取、JWT/kb 权限校验在图入口之前完成；
        SSE 六事件协议与事件负载结构与 native 完全一致，前端零改动。
        """
        user_id = current_user.id if current_user else None
        received_at = datetime.utcnow()
        start_total = time.perf_counter()
        conversation_id = None
        kb_id = "default"

        try:
            yield StreamEvent(
                type="status",
                data={"step": "received", "message": "已收到，我先查一下知识库…"},
            )
            logger.info(
                "chat_stream_step_start",
                step="received",
                conversation_id=conversation_id,
                orchestration_mode="agentic",
            )

            conversation_id = request.conversation_id or await asyncio.to_thread(
                self.conversation_store.create,
                user_id=user_id,
            )
            history = await asyncio.to_thread(self.get_history, conversation_id)
            kb_id = await self._resolve_kb_id(request, current_user)
            logger.info(
                "agentic_stream_entry",
                conversation_id=conversation_id,
                kb_id=kb_id,
                message_count=len(history),
           )

            deps = AgenticGraphDeps(
                retrieval_pipeline=self.retrieval_pipeline,
                generation_pipeline=self.generation_pipeline,
                query_rewrite_stage=self.query_rewrite_stage,
                grade_stage=self.grade_stage,
                plan_stage=self.plan_stage,
                multi_hop_decompose_stage=self.multi_hop_decompose_stage,
            )
            runner = await AgentGraphRunner.create(deps, settings_service=self.settings_service)
            try:
                async for event in runner.stream(
                    {
                        "question": request.question,
                        "conversation_id": conversation_id,
                        "history": history,
                        "kb_id": kb_id,
                    },
                    thread_id=conversation_id,
                ):
                    yield event
            finally:
                await runner.close()

            final = runner.final_state
            citations = final.get("citations", [])
            is_refusal = final.get("is_refusal", False)
            is_stale = final.get("is_stale", False)
            full_answer = final.get("answer", "")
            retrieval_results = final.get("retrieval_results", [])
            is_fallback = final.get("is_fallback", False)
            query = final.get("rewritten_query", request.question)
            tool_trace = final.get("tool_trace", [])

            # 中断时暂不持久化，等待恢复执行后再统一落库
            if runner.interrupted:
                logger.info(
                    "agentic_stream_interrupted",
                    conversation_id=conversation_id,
                    thread_id=conversation_id,
                )
                return

            latency_ms_total = int((time.perf_counter() - start_total) * 1000)

            asyncio.create_task(
                asyncio.to_thread(
                    self._persist_chat,
                    conversation_id=conversation_id,
                    user_id=user_id,
                    question=request.question,
                    full_answer=full_answer,
                    citations=citations,
                    is_refusal=is_refusal,
                    is_stale=is_stale,
                )
            )

            graphrag_enabled = bool(kb_id and await self._is_shadow_mode_enabled(kb_id))
            graphrag_used = False
            if kb_id and await self._is_shadow_mode_enabled(kb_id):
                asyncio.create_task(
                    self._record_shadow_async(
                        kb_id=kb_id,
                        user_id=user_id,
                        question=request.question,
                        retrieval_results=retrieval_results,
                        is_fallback=is_fallback,
                        history=history,
                        vector_answer=full_answer,
                    )
                )
                graphrag_used = graphrag_enabled

            asyncio.create_task(
                asyncio.to_thread(
                    self._log_query,
                    user_id=user_id,
                    received_at=received_at,
                    original_question=request.question,
                    rewritten_question=query,
                    kb_id=kb_id,
                    retrieval_adapter=self.settings_service.get_runtime_value("retrieval_adapter"),
                    is_fallback=is_fallback,
                    max_score=final.get("max_score") if retrieval_results else None,
                    retrieval_results=retrieval_results,
                    answer=full_answer,
                    citations=citations,
                    is_refusal=is_refusal,
                    is_stale=is_stale,
                    graphrag_enabled=graphrag_enabled,
                    graphrag_used=graphrag_used,
                    latency_ms_rewrite=self._trace_latency(tool_trace, "rewrite"),
                    latency_ms_retrieve=self._trace_latency(tool_trace, "retrieve"),
                    latency_ms_generate=self._trace_latency(tool_trace, "generate"),
                    latency_ms_total=latency_ms_total,
                    tool_trace=tool_trace,
                    retrieval_metadata=final.get("retrieval_metadata"),
                )
            )
        except Exception as exc:
            logger.error(
                "chat_stream_failed",
                conversation_id=conversation_id,
                user_id=user_id,
                error=str(exc),
                orchestration_mode="agentic",
            )
            yield StreamEvent(
                type="error",
                data={
                    "conversation_id": conversation_id,
                    "message": str(exc),
                },
            )

    @staticmethod
    def _trace_latency(tool_trace: list[dict], node: str) -> int | None:
        for entry in tool_trace or []:
            if entry.get("node") == node:
                return entry.get("latency_ms")
        return None

    async def get_agentic_state(self, conversation_id: str) -> dict:
        """获取指定会话当前 agentic 编排状态快照。"""
        deps = AgenticGraphDeps(
            retrieval_pipeline=self.retrieval_pipeline,
            generation_pipeline=self.generation_pipeline,
            query_rewrite_stage=self.query_rewrite_stage,
            grade_stage=self.grade_stage,
            plan_stage=self.plan_stage,
            multi_hop_decompose_stage=self.multi_hop_decompose_stage,
        )
        runner = await AgentGraphRunner.create(deps, settings_service=self.settings_service)
        try:
            return await runner.get_state(conversation_id)
        finally:
            await runner.close()

    async def resume_agentic_stream(
        self,
        conversation_id: str,
        resume_payload: dict | None = None,
    ) -> AsyncIterator[StreamEvent]:
        """恢复被中断的 agentic 编排流并继续输出 SSE 事件。"""
        user_id = None
        received_at = datetime.utcnow()
        start_total = time.perf_counter()
        full_answer = ""
        citations = []
        is_refusal = False
        is_stale = False
        retrieval_results = []
        is_fallback = False
        query = ""
        tool_trace = []

        try:
            yield StreamEvent(
                type="status",
                data={
                    "step": "resuming",
                    "message": "正在恢复编排执行…",
                    "conversation_id": conversation_id,
                },
            )

            deps = AgenticGraphDeps(
                retrieval_pipeline=self.retrieval_pipeline,
                generation_pipeline=self.generation_pipeline,
                query_rewrite_stage=self.query_rewrite_stage,
                grade_stage=self.grade_stage,
                plan_stage=self.plan_stage,
                multi_hop_decompose_stage=self.multi_hop_decompose_stage,
            )
            runner = await AgentGraphRunner.create(deps, settings_service=self.settings_service)
            try:
                async for event in runner.resume(
                    thread_id=conversation_id,
                    resume_payload=resume_payload,
                ):
                    if event.type == "chunk":
                        full_answer += event.data.get("content", "")
                    elif event.type == "citations":
                        citations = event.data.get("citations", [])
                        is_refusal = event.data.get("is_refusal", False)
                        is_stale = event.data.get("is_stale", False)
                    yield event
            finally:
                await runner.close()

            final = runner.final_state
            citations = final.get("citations", citations)
            is_refusal = final.get("is_refusal", is_refusal)
            is_stale = final.get("is_stale", is_stale)
            full_answer = final.get("answer", full_answer)
            retrieval_results = final.get("retrieval_results", retrieval_results)
            is_fallback = final.get("is_fallback", is_fallback)
            query = final.get("rewritten_query", query)
            tool_trace = final.get("tool_trace", tool_trace)

            if runner.interrupted:
                logger.info(
                    "agentic_resume_interrupted_again",
                    conversation_id=conversation_id,
                )
                return

            latency_ms_total = int((time.perf_counter() - start_total) * 1000)

            asyncio.create_task(
                asyncio.to_thread(
                    self._persist_chat,
                    conversation_id=conversation_id,
                    user_id=user_id,
                    question=final.get("question", ""),
                    full_answer=full_answer,
                    citations=citations,
                    is_refusal=is_refusal,
                    is_stale=is_stale,
                )
            )

            graphrag_enabled = bool(
                final.get("kb_id") and await self._is_shadow_mode_enabled(final.get("kb_id"))
            )
            graphrag_used = False
            if graphrag_enabled:
                asyncio.create_task(
                    self._record_shadow_async(
                        kb_id=final.get("kb_id"),
                        user_id=user_id,
                        question=final.get("question", ""),
                        retrieval_results=retrieval_results,
                        is_fallback=is_fallback,
                        history=final.get("history", []),
                        vector_answer=full_answer,
                    )
                )
                graphrag_used = graphrag_enabled

            asyncio.create_task(
                asyncio.to_thread(
                    self._log_query,
                    user_id=user_id,
                    received_at=received_at,
                    original_question=final.get("question", ""),
                    rewritten_question=query,
                    kb_id=final.get("kb_id", "default"),
                    retrieval_adapter=self.settings_service.get_runtime_value("retrieval_adapter"),
                    is_fallback=is_fallback,
                    max_score=final.get("max_score") if retrieval_results else None,
                    retrieval_results=retrieval_results,
                    answer=full_answer,
                    citations=citations,
                    is_refusal=is_refusal,
                    is_stale=is_stale,
                    graphrag_enabled=graphrag_enabled,
                    graphrag_used=graphrag_used,
                    latency_ms_rewrite=self._trace_latency(tool_trace, "rewrite"),
                    latency_ms_retrieve=self._trace_latency(tool_trace, "retrieve"),
                    latency_ms_generate=self._trace_latency(tool_trace, "generate"),
                    latency_ms_total=latency_ms_total,
                    tool_trace=tool_trace,
                    retrieval_metadata=final.get("retrieval_metadata"),
                )
            )
        except Exception as exc:
            logger.error(
                "agentic_resume_failed",
                conversation_id=conversation_id,
                error=str(exc),
            )
            yield StreamEvent(
                type="error",
                data={
                    "conversation_id": conversation_id,
                    "message": str(exc),
                },
            )
