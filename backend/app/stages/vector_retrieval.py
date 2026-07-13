
from pydantic import BaseModel

from app.clients.model_client import ModelClient
from app.stages.base import AbstractStage, RetrievalResult
from app.stores.milvus import MilvusStore


class VectorRetrievalInput(BaseModel):
    query: str
    top_k: int = 50


class VectorRetrievalOutput(BaseModel):
    results: list[RetrievalResult]


class VectorRetrievalStage(AbstractStage[VectorRetrievalInput, VectorRetrievalOutput]):
    """向量语义检索：查询向量化后从 Milvus 召回候选片段。"""

    def __init__(self, model_client: ModelClient, milvus_store: MilvusStore):
        self.model_client = model_client
        self.milvus_store = milvus_store

    @property
    def name(self) -> str:
        return "vector_retrieval"

    def execute(
        self,
        input_data: VectorRetrievalInput,
        model_name: str | None = None,
    ) -> VectorRetrievalOutput:
        query_embedding = self.model_client.embed([input_data.query], model=model_name)[0]
        results = self.milvus_store.search(query_embedding, top_k=input_data.top_k)
        return VectorRetrievalOutput(results=results)
