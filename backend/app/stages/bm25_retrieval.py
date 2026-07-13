
from pydantic import BaseModel

from app.stages.base import AbstractStage, RetrievalResult
from app.stores.bm25_store import BM25Store


class BM25RetrievalInput(BaseModel):
    query: str
    top_k: int = 50


class BM25RetrievalOutput(BaseModel):
    results: list[RetrievalResult]


class BM25RetrievalStage(AbstractStage[BM25RetrievalInput, BM25RetrievalOutput]):
    """关键词检索：从 BM25 索引召回候选片段。"""

    def __init__(self, bm25_store: BM25Store):
        self.bm25_store = bm25_store

    @property
    def name(self) -> str:
        return "bm25_retrieval"

    def execute(self, input_data: BM25RetrievalInput) -> BM25RetrievalOutput:
        raw_results = self.bm25_store.search(input_data.query, top_k=input_data.top_k)

        # 将 BM25 原始分数归一化到 0-1，便于与向量分数融合
        max_score = max((score for _, score in raw_results), default=1.0)
        if max_score == 0:
            max_score = 1.0

        results: list[RetrievalResult] = []
        for chunk_id, score in raw_results:
            chunk = self.bm25_store.get_chunk(chunk_id)
            if not chunk:
                continue
            results.append(
                RetrievalResult(
                    chunk_id=chunk.chunk_id,
                    content=chunk.content,
                    source_type=chunk.source_type,
                    title=chunk.title,
                    updated_at=chunk.updated_at,
                    source_id=chunk.source_id,
                    score=score / max_score,
                )
            )
        return BM25RetrievalOutput(results=results)
