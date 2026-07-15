
from collections.abc import Callable

from pydantic import BaseModel

from app.clients.model_client import ModelClient
from app.config import Settings
from app.stages.base import AbstractStage, Chunk, EmbeddingResult


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
        # DashScope text-embedding-v3 单次最多 10 条，默认从配置读取
        self.batch_size = batch_size or (settings.embedding_batch_size if settings else 10)

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
            texts = [c.content for c in batch]
            vectors = self.model_client.embed(texts, model=model_name)
            for chunk, vector in zip(batch, vectors):
                embeddings.append(
                    EmbeddingResult(chunk_id=chunk.chunk_id, embedding=vector)
                )
            if on_progress:
                on_progress(min(i + self.batch_size, total), total)

        return EmbeddingOutput(embeddings=embeddings)
