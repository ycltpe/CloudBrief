from abc import ABC, abstractmethod
from datetime import datetime
from typing import Generic, TypeVar

from pydantic import BaseModel


class Document(BaseModel):
    """知识源解析后的原始文档单元。"""

    content: str
    source_type: str  # help_doc | changelog | ticket | faq
    title: str
    updated_at: datetime
    source_id: str  # 唯一标识，如 help_docs/export-guide.md


class Chunk(BaseModel):
    """切分后的最小检索单元。"""

    chunk_id: str  # {source_type}:{source_id}:{chunk_index}
    content: str
    source_type: str
    title: str
    updated_at: datetime
    source_id: str
    chunk_index: int


class EmbeddingResult(BaseModel):
    chunk_id: str
    embedding: list[float]


class RetrievalResult(BaseModel):
    chunk_id: str
    content: str
    source_type: str
    title: str
    updated_at: datetime
    source_id: str
    score: float  # 该 Stage 输出的分数


InputT = TypeVar("InputT", bound=BaseModel)
OutputT = TypeVar("OutputT", bound=BaseModel)


class AbstractStage(ABC, Generic[InputT, OutputT]):
    """所有 Stage 的统一接口。"""

    @property
    @abstractmethod
    def name(self) -> str:
        ...

    @abstractmethod
    def execute(self, input_data: InputT) -> OutputT:
        ...


class StageInput(BaseModel):
    documents: list[Document]


class StageOutput(BaseModel):
    chunks: list[Chunk]
