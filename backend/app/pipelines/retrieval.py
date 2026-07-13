from dataclasses import dataclass

import structlog

from app.config import get_settings
from app.metrics import RECALL_COUNT, RERANK_MAX_SCORE, RETRIEVAL_LATENCY
from app.services.settings_service import SettingsService
from app.stages.adapters.lc_retrieval import (
    LangChainRetrievalStage,
    LCRetrievalInput,
)
from app.stages.adapters.reranker_adapter import create_reranker_adapter
from app.stages.base import RetrievalResult
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


class RetrievalPipeline:
    """检索管线：根据配置使用 Native 主路径或 LangChain 适配器。"""

    def __init__(self, model_client):
        self.model_client = model_client
        self.settings = get_settings()
        self.index_metadata_store = IndexMetadataStore()
        self.settings_service = SettingsService()

    def retrieve(
        self,
        query: str,
        top_k: int = 50,
        top_n: int = 5,
        kb_id: str = "default",
    ) -> RetrievalPipelineOutput:
        import time

        start = time.perf_counter()
        adapter = self.settings.retrieval_adapter

        if adapter == "langchain":
            stage = LangChainRetrievalStage()
            output = stage.execute(
                LCRetrievalInput(query=query, top_k=top_k, top_n=top_n, kb_id=kb_id)
            )
            return RetrievalPipelineOutput(
                results=output.results,
                is_fallback=output.is_fallback,
            )

        active = self.index_metadata_store.get_active(kb_id)
        if not active:
            raise RuntimeError(f"No active index found for kb {kb_id}. Please rebuild index first.")

        runtime_embedding_model = self.settings_service.get_runtime_value("embedding_model")

        milvus_store = MilvusStore(self.settings.milvus_uri, active.collection_name)
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
                VectorRetrievalInput(query=query, top_k=top_k),
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
                k=60,
            )
        ).fused_results
        reranked = rerank_stage.execute(
            RerankingInput(query=query, candidates=fused, top_n=top_n)
        )
        latency_ms = int((time.perf_counter() - start) * 1000)

        RETRIEVAL_LATENCY.labels(adapter=adapter, kb_id=kb_id, fallback=str(is_fallback)).observe(latency_ms)
        RECALL_COUNT.labels(adapter=adapter, kb_id=kb_id, fallback=str(is_fallback)).observe(len(reranked.reranked_results))
        if reranked.reranked_results:
            RERANK_MAX_SCORE.labels(adapter=adapter, kb_id=kb_id, fallback=str(is_fallback)).set(
                max(r.score for r in reranked.reranked_results)
            )

        return RetrievalPipelineOutput(
            results=reranked.reranked_results,
            is_fallback=is_fallback or reranked.is_fallback,
        )
