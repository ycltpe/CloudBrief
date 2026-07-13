import httpx
import structlog
from pydantic import BaseModel

from app.metrics import ERROR_TOTAL
from app.stages.adapters.reranker_adapter import RerankerAdapter
from app.stages.base import AbstractStage, RetrievalResult

logger = structlog.get_logger()


class RerankingInput(BaseModel):
    query: str
    candidates: list[RetrievalResult]
    top_n: int = 5


class RerankingOutput(BaseModel):
    reranked_results: list[RetrievalResult]
    max_score: float
    is_fallback: bool = False


class RerankingStage(AbstractStage[RerankingInput, RerankingOutput]):
    """使用配置的重排模型对候选片段精排；API 不可用时回退到融合分数。"""

    def __init__(self, reranker: RerankerAdapter):
        self.reranker = reranker

    @property
    def name(self) -> str:
        return "reranking"

    def execute(self, input_data: RerankingInput) -> RerankingOutput:
        if not input_data.candidates:
            return RerankingOutput(reranked_results=[], max_score=0.0)

        try:
            passages = [c.content for c in input_data.candidates]
            scored = self.reranker.rerank(
                input_data.query,
                passages,
                top_n=input_data.top_n,
            )

            if not scored:
                logger.warning("rerank_returned_empty_scores_falling_back")
                fallback = sorted(
                    input_data.candidates,
                    key=lambda r: r.score,
                    reverse=True,
                )[: input_data.top_n]
                max_score = max((r.score for r in fallback), default=0.0)
                return RerankingOutput(
                    reranked_results=fallback,
                    max_score=max_score,
                    is_fallback=True,
                )

            result_map = {c.chunk_id: c for c in input_data.candidates}
            reranked: list[RetrievalResult] = []
            for idx, score in scored:
                base = result_map[input_data.candidates[idx].chunk_id]
                reranked.append(
                    RetrievalResult(
                        chunk_id=base.chunk_id,
                        content=base.content,
                        source_type=base.source_type,
                        title=base.title,
                        updated_at=base.updated_at,
                        source_id=base.source_id,
                        score=score,
                    )
                )

            max_score = max((r.score for r in reranked), default=0.0)
            return RerankingOutput(reranked_results=reranked, max_score=max_score)
        except (httpx.HTTPStatusError, httpx.RequestError, ValueError) as exc:
            logger.warning(
                "rerank_api_unavailable_falling_back",
                error_type=type(exc).__name__,
                error=str(exc),
            )
            ERROR_TOTAL.labels(code="RERANKER_FALLBACK", component="reranking").inc()
            # 回退：按融合分数截断 top_n
            fallback = sorted(
                input_data.candidates,
                key=lambda r: r.score,
                reverse=True,
            )[: input_data.top_n]
            max_score = max((r.score for r in fallback), default=0.0)
            return RerankingOutput(
                reranked_results=fallback,
                max_score=max_score,
                is_fallback=True,
            )
