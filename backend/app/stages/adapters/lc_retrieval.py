from langchain_community.retrievers import BM25Retriever
from langchain_community.vectorstores.milvus import Milvus
from langchain_core.documents import Document as LCDocument
from langchain_openai import OpenAIEmbeddings
from pydantic import BaseModel

from app.config import get_settings
from app.services.settings_service import SettingsService
from app.stages.adapters.reranker_adapter import create_reranker_adapter
from app.stages.base import AbstractStage, RetrievalResult
from app.stages.hybrid_fusion import HybridFusionInput, HybridFusionStage
from app.stages.reranking import RerankingInput, RerankingStage
from app.stores.bm25_store import BM25Store
from app.stores.index_metadata import IndexMetadataStore


class LCRetrievalInput(BaseModel):
    query: str
    top_k: int = 50
    top_n: int = 5
    kb_id: str = "default"


class LCRetrievalOutput(BaseModel):
    results: list[RetrievalResult]
    is_fallback: bool = False


class LangChainRetrievalStage(AbstractStage[LCRetrievalInput, LCRetrievalOutput]):
    """LangChain 检索适配器：Milvus + BM25 → RRF(k=60) → reranker → Top-N。

    与 Native 路径保持等价流程，仅在召回阶段使用 LangChain 生态组件。
    """

    def __init__(self):
        self.settings = get_settings()
        self.index_metadata_store = IndexMetadataStore()
        self.settings_service = SettingsService()

    @property
    def name(self) -> str:
        return "lc_retrieval"

    @staticmethod
    def _doc_to_result(doc: LCDocument, score: float = 0.0) -> RetrievalResult:
        meta = doc.metadata
        updated_at = meta.get("updated_at")
        if hasattr(updated_at, "isoformat"):
            updated_at = updated_at.isoformat()
        return RetrievalResult(
            chunk_id=meta.get("chunk_id", ""),
            content=doc.page_content,
            source_type=meta.get("source_type", ""),
            title=meta.get("title", ""),
            updated_at=updated_at,
            source_id=meta.get("source_id", ""),
            score=score,
        )

    def _vector_results(self, query: str, top_k: int, kb_id: str = "default") -> list[RetrievalResult]:
        active = self.index_metadata_store.get_active(kb_id)
        embeddings = OpenAIEmbeddings(
            model=self.settings_service.get_runtime_value("embedding_model"),
            base_url=str(self.settings_service.get_runtime_value("embedding_base_url")),
            api_key=self.settings_service.get_runtime_value("embedding_api_key"),
        )
        milvus_store = Milvus(
            embedding_function=embeddings,
            collection_name=active.collection_name,
            connection_args={"uri": self.settings_service.get_runtime_value("milvus_uri")},
            auto_id=False,
            primary_field="chunk_id",
            text_field="content",
            vector_field="embedding",
        )
        milvus_retriever = milvus_store.as_retriever(search_kwargs={"k": top_k})
        docs = milvus_retriever.invoke(query)
        return [self._doc_to_result(doc) for doc in docs]

    def _bm25_results(self, query: str, top_k: int, kb_id: str = "default") -> list[RetrievalResult]:
        active = self.index_metadata_store.get_active(kb_id)
        bm25_store = BM25Store(active.bm25_index_path)
        bm25_store.load()
        lc_docs = [
            LCDocument(
                page_content=chunk.content,
                metadata={
                    "chunk_id": chunk.chunk_id,
                    "source_type": chunk.source_type,
                    "title": chunk.title,
                    "updated_at": chunk.updated_at,
                    "source_id": chunk.source_id,
                },
            )
            for chunk in bm25_store._chunks
        ]
        bm25_retriever = BM25Retriever.from_documents(lc_docs, k=top_k)
        docs = bm25_retriever.invoke(query)
        return [self._doc_to_result(doc) for doc in docs]

    def execute(self, input_data: LCRetrievalInput) -> LCRetrievalOutput:
        active = self.index_metadata_store.get_active(input_data.kb_id)
        if not active:
            raise RuntimeError(f"No active index found for kb {input_data.kb_id}. Please rebuild index first.")

        # 1. 两路召回
        vector_results = self._vector_results(input_data.query, input_data.top_k, input_data.kb_id)
        bm25_results = self._bm25_results(input_data.query, input_data.top_k, input_data.kb_id)

        # 2. RRF(k=60) 融合
        fusion_stage = HybridFusionStage()
        fused = fusion_stage.execute(
            HybridFusionInput(
                vector_results=vector_results,
                bm25_results=bm25_results,
                top_k=input_data.top_k,
                k=60,
            )
        ).fused_results

        # 3. reranker 精排
        reranker = create_reranker_adapter(self.settings, self.settings_service)
        rerank_stage = RerankingStage(reranker)
        reranked = rerank_stage.execute(
            RerankingInput(
                query=input_data.query,
                candidates=fused,
                top_n=input_data.top_n,
            )
        )

        return LCRetrievalOutput(
            results=reranked.reranked_results,
            is_fallback=reranked.is_fallback,
        )
