import random
from dataclasses import dataclass
from datetime import datetime, timedelta

import structlog

from app.config import get_settings
from app.metrics import RECALL_COUNT, RERANK_MAX_SCORE, RETRIEVAL_LATENCY
from app.services.settings_service import SettingsService
from app.stages.adapters.lc_retrieval import (
    LangChainRetrievalStage,
    LCRetrievalInput,
)
from app.stages.adapters.reranker_adapter import create_reranker_adapter
from app.stages.base import RetrievalCascadeMetadata, RetrievalResult
from app.stages.bm25_retrieval import BM25RetrievalInput, BM25RetrievalStage
from app.stages.hybrid_fusion import HybridFusionInput, HybridFusionStage
from app.stages.reranking import RerankingInput, RerankingStage
from app.stages.vector_retrieval import VectorRetrievalInput, VectorRetrievalStage
from app.stores.bm25_store import BM25Store
from app.stores.index_metadata import IndexMetadataStore
from app.stores.milvus import MilvusStore

logger = structlog.get_logger()


@dataclass
class RetrievalPipelineOutput:
    results: list[RetrievalResult]
    is_fallback: bool = False
    retrieval_metadata: RetrievalCascadeMetadata | None = None


class RetrievalPipeline:
    """检索管线：根据配置使用 Native 主路径或 LangChain 适配器。"""

    RRF_K = 60

    def __init__(self, model_client):
        self.model_client = model_client
        self.settings = get_settings()
        self.index_metadata_store = IndexMetadataStore()
        self.settings_service = SettingsService()

    @staticmethod
    def _build_freshness_filter(stale_threshold_days: int) -> str | None:
        """根据时效阈值构建 Milvus 标量过滤表达式。"""
        if stale_threshold_days <= 0:
            return None
        cutoff = datetime.utcnow() - timedelta(days=stale_threshold_days)
        return f'updated_at >= "{cutoff.isoformat()}"'

    @staticmethod
    def _is_fresh(result: RetrievalResult, cutoff: datetime) -> bool:
        """判断单条检索结果是否在 cutoff 之后更新。"""
        updated_at = result.updated_at
        if isinstance(updated_at, datetime):
            return updated_at >= cutoff
        if isinstance(updated_at, str):
            try:
                return datetime.fromisoformat(updated_at) >= cutoff
            except ValueError:
                return True
        return True

    @staticmethod
    def _combine_filters(*filters: str | None) -> str | None:
        """把多个 filter 用 AND 连接，自动过滤空值。"""
        parts = [f.strip() for f in filters if f and f.strip()]
        if not parts:
            return None
        if len(parts) == 1:
            return parts[0]
        return " AND ".join(f"({p})" for p in parts)

    def _build_retrieval_metadata(
        self,
        *,
        active,
        vector_results: list[RetrievalResult],
        bm25_results: list[RetrievalResult],
        combined_filter: str | None,
        reranked,
        shadow: dict | None = None,
    ) -> RetrievalCascadeMetadata:
        """根据各级 Stage 输出构造级联元数据。"""
        configured_provider = self.settings_service.get_runtime_value("reranker_provider")
        is_fallback = reranked.is_fallback
        rerank_provider = f"{configured_provider}:fallback" if is_fallback else configured_provider
        index_type = getattr(active, "index_type", None)
        if not index_type:
            index_type = "IVF_FLAT"
        return RetrievalCascadeMetadata(
            vector_hits=len(vector_results),
            bm25_hits=len(bm25_results),
            rrf_k=self.RRF_K,
            rerank_provider=rerank_provider,
            applied_filter=combined_filter,
            index_version=active.collection_name,
            index_type=index_type,
            shadow=shadow,
        )

    def _run_shadow_retrieval(
        self,
        *,
        active,
        query: str,
        top_k: int,
        combined_filter: str | None,
        runtime_embedding_model: str,
    ) -> dict | None:
        """Shadow 路径：用 shadow collection 仅跑向量检索，失败不影响主路径。"""
        shadow_collection_name = getattr(active, "shadow_collection_name", None)
        shadow_index_type = getattr(active, "shadow_index_type", None)
        if not shadow_collection_name or not shadow_index_type:
            return None

        import time

        start = time.perf_counter()
        try:
            shadow_milvus = MilvusStore(
                self.settings_service.get_runtime_value("milvus_uri"),
                shadow_collection_name,
                index_type=shadow_index_type,
            )
            shadow_vector_stage = VectorRetrievalStage(self.model_client, shadow_milvus)
            shadow_vector_results = shadow_vector_stage.execute(
                VectorRetrievalInput(query=query, top_k=top_k, filter=combined_filter),
                model_name=runtime_embedding_model,
            ).results
            latency_ms = int((time.perf_counter() - start) * 1000)
            return {
                "enabled": True,
                "index_type": shadow_index_type,
                "index_version": shadow_collection_name,
                "vector_hits": len(shadow_vector_results),
                "latency_ms": latency_ms,
                "error": None,
                "top5_chunk_ids": [r.chunk_id for r in shadow_vector_results[:5]],
            }
        except Exception as exc:
            latency_ms = int((time.perf_counter() - start) * 1000)
            logger.warning(
                "shadow_retrieval_failed",
                shadow_collection=shadow_collection_name,
                error=str(exc),
            )
            return {
                "enabled": True,
                "index_type": shadow_index_type,
                "index_version": shadow_collection_name,
                "vector_hits": 0,
                "latency_ms": latency_ms,
                "error": str(exc),
                "top5_chunk_ids": [],
            }

    def retrieve(
        self,
        query: str,
        top_k: int = 50,
        top_n: int = 5,
        kb_id: str = "default",
        filter: str | None = None,
    ) -> RetrievalPipelineOutput:
        import time

        start = time.perf_counter()
        adapter = self.settings_service.get_runtime_value("retrieval_adapter")
        orchestration_mode = self.settings_service.get_runtime_value("orchestration_mode")

        if adapter == "langchain":
            stage = LangChainRetrievalStage()
            output = stage.execute(
                LCRetrievalInput(query=query, top_k=top_k, top_n=top_n, kb_id=kb_id)
            )
            return RetrievalPipelineOutput(
                results=output.results,
                is_fallback=output.is_fallback,
                retrieval_metadata=output.retrieval_metadata,
            )

        stale_threshold_days = self.settings_service.get_runtime_value("stale_threshold_days")
        freshness_filter = self._build_freshness_filter(stale_threshold_days)
        combined_filter = self._combine_filters(freshness_filter, filter)

        active = self.index_metadata_store.get_active(kb_id)
        if not active:
            raise RuntimeError(f"No active index found for kb {kb_id}. Please rebuild index first.")

        runtime_embedding_model = self.settings_service.get_runtime_value("embedding_model")

        milvus_store = MilvusStore(self.settings_service.get_runtime_value("milvus_uri"), active.collection_name)
        bm25_store = BM25Store(active.bm25_index_path)
        bm25_store.load()

        vector_stage = VectorRetrievalStage(self.model_client, milvus_store)
        bm25_stage = BM25RetrievalStage(bm25_store)
        fusion_stage = HybridFusionStage()
        reranker = create_reranker_adapter(self.settings, self.settings_service)
        rerank_stage = RerankingStage(reranker)

        is_fallback = False
        vector_results: list[RetrievalResult] = []
        try:
            vector_results = vector_stage.execute(
                VectorRetrievalInput(query=query, top_k=top_k, filter=combined_filter),
                model_name=runtime_embedding_model,
            ).results
        except Exception as exc:
            logger.warning("milvus_vector_retrieval_failed", kb_id=kb_id, error=str(exc))
            is_fallback = True

        bm25_results = bm25_stage.execute(
            BM25RetrievalInput(query=query, top_k=top_k)
        ).results

        fused = fusion_stage.execute(
            HybridFusionInput(
                vector_results=vector_results,
                bm25_results=bm25_results,
                top_k=top_k,
                k=self.RRF_K,
            )
        ).fused_results
        reranked = rerank_stage.execute(
            RerankingInput(query=query, candidates=fused, top_n=top_n)
        )

        # 检索期时效过滤兜底：剔除 BM25 等路径可能引入的过期片段
        cutoff_dt = datetime.utcnow() - timedelta(days=stale_threshold_days)
        filtered_results = [r for r in reranked.reranked_results if self._is_fresh(r, cutoff_dt)]

        # Shadow 检索切流：按 shadow_ratio 决定是否执行对照路径
        shadow_ratio = self.settings_service.get_runtime_value("shadow_ratio") or 0
        shadow: dict | None = None
        if shadow_ratio > 0 and random.uniform(0, 100) < shadow_ratio:
            shadow = self._run_shadow_retrieval(
                active=active,
                query=query,
                top_k=top_k,
                combined_filter=combined_filter,
                runtime_embedding_model=runtime_embedding_model,
            )

        retrieval_metadata = self._build_retrieval_metadata(
            active=active,
            vector_results=vector_results,
            bm25_results=bm25_results,
            combined_filter=combined_filter,
            reranked=reranked,
            shadow=shadow,
        )

        latency_ms = int((time.perf_counter() - start) * 1000)

        RETRIEVAL_LATENCY.labels(adapter=adapter, kb_id=kb_id, fallback=str(is_fallback), orchestration_mode=orchestration_mode).observe(latency_ms)
        RECALL_COUNT.labels(adapter=adapter, kb_id=kb_id, fallback=str(is_fallback), orchestration_mode=orchestration_mode).observe(len(filtered_results))
        if filtered_results:
            RERANK_MAX_SCORE.labels(adapter=adapter, kb_id=kb_id, fallback=str(is_fallback), orchestration_mode=orchestration_mode).set(
                max(r.score for r in filtered_results)
            )

        return RetrievalPipelineOutput(
            results=filtered_results,
            is_fallback=is_fallback or reranked.is_fallback,
            retrieval_metadata=retrieval_metadata,
        )
