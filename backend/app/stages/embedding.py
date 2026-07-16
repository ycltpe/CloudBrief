

from collections.abc import Callable

import structlog
from pydantic import BaseModel

from app.clients.model_client import ModelClient
from app.config import Settings
from app.stages.base import AbstractStage, Chunk, EmbeddingResult

logger = structlog.get_logger()


class EmbeddingInput(BaseModel):
    chunks: list[Chunk]


class EmbeddingOutput(BaseModel):
    embeddings: list[EmbeddingResult]


class EmbeddingStage(AbstractStage[EmbeddingInput, EmbeddingOutput]):
    """为 Chunk 批量生成 Embedding 向量。"""

    def __init__(
        self,
        model_client: ModelClient,
        settings: Settings | None = None,
        batch_size: int | None = None,
    ):
        self.model_client = model_client
        # DashScope text-embedding-v3 单次最多 10 条；批大小走运行期配置（DB → .env → 默认）
        if batch_size is None:
            from app.services.settings_service import SettingsService

            batch_size = SettingsService().get_runtime_value("embedding_batch_size")
        self.batch_size = batch_size

    @property
    def name(self) -> str:
        return "embedding"

    def execute(
        self,
        input_data: EmbeddingInput,
        model_name: str | None = None,
        on_progress: Callable[[int, int], None] | None = None,
    ) -> EmbeddingOutput:
        chunks = input_data.chunks
        embeddings: list[EmbeddingResult] = []
        total = len(chunks)

        for i in range(0, total, self.batch_size):
            batch = chunks[i : i + self.batch_size]
            # 空文本会被 Embedding API 整批拒绝（输入长度下限为 1），逐条防御性跳过；
            # 调用方按 chunk_id 对齐向量，跳过的 chunk 不会进入索引
            non_empty = [c for c in batch if c.content.strip()]
            if len(non_empty) < len(batch):
                logger.warning(
                    "embedding_empty_chunk_skipped",
                    skipped=len(batch) - len(non_empty),
                )
            if not non_empty:
                if on_progress:
                    on_progress(min(i + self.batch_size, total), total)
                continue
            texts = [c.content for c in non_empty]
            vectors = self.model_client.embed(texts, model=model_name)
            for chunk, vector in zip(non_empty, vectors):
                embeddings.append(
                    EmbeddingResult(chunk_id=chunk.chunk_id, embedding=vector)
                )
            if on_progress:
                on_progress(min(i + self.batch_size, total), total)

        return EmbeddingOutput(embeddings=embeddings)
