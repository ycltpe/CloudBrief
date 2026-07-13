from pydantic import BaseModel

from app.stages.base import AbstractStage, RetrievalResult


class HybridFusionInput(BaseModel):
    vector_results: list[RetrievalResult]
    bm25_results: list[RetrievalResult]
    top_k: int = 50
    k: int = 60


class HybridFusionOutput(BaseModel):
    fused_results: list[RetrievalResult]


class HybridFusionStage(AbstractStage[HybridFusionInput, HybridFusionOutput]):
    """RRF 融合：合并向量检索与关键词检索结果。"""

    @property
    def name(self) -> str:
        return "hybrid_fusion"

    def execute(self, input_data: HybridFusionInput) -> HybridFusionOutput:
        scores: dict[str, float] = {}
        result_map: dict[str, RetrievalResult] = {}

        def _add(results: list[RetrievalResult]) -> None:
            for rank, result in enumerate(results, start=1):
                result_map[result.chunk_id] = result
                scores[result.chunk_id] = scores.get(result.chunk_id, 0.0) + 1.0 / (
                    input_data.k + rank
                )

        _add(input_data.vector_results)
        _add(input_data.bm25_results)

        # 按 RRF 分数降序
        sorted_ids = sorted(scores.keys(), key=lambda cid: scores[cid], reverse=True)

        # 归一化到 [0, 1]，避免原始 RRF 分数远低于 refusal_threshold
        max_score = max(scores.values()) if scores else 1.0

        fused: list[RetrievalResult] = []
        for chunk_id in sorted_ids[: input_data.top_k]:
            base = result_map[chunk_id]
            fused.append(
                RetrievalResult(
                    chunk_id=base.chunk_id,
                    content=base.content,
                    source_type=base.source_type,
                    title=base.title,
                    updated_at=base.updated_at,
                    source_id=base.source_id,
                    score=scores[chunk_id] / max_score,
                )
            )
        return HybridFusionOutput(fused_results=fused)
