from datetime import datetime
from typing import Any

from pymilvus import DataType, MilvusClient

from app.stages.base import Chunk, RetrievalResult


class MilvusStore:
    """Milvus 向量存储封装，使用 MilvusClient 简化 API。"""

    def __init__(self, uri: str, collection_name: str, dim: int = 1536):
        self.client = MilvusClient(uri=uri)
        self.collection_name = collection_name
        self.dim = dim

    def create_collection(self) -> None:
        if self.client.has_collection(collection_name=self.collection_name):
            self.client.drop_collection(collection_name=self.collection_name)

        schema = self.client.create_schema(
            auto_id=False,
            enable_dynamic_field=False,
        )
        schema.add_field(field_name="chunk_id", datatype=DataType.VARCHAR, max_length=256, is_primary=True)
        schema.add_field(field_name="source_type", datatype=DataType.VARCHAR, max_length=64)
        schema.add_field(field_name="title", datatype=DataType.VARCHAR, max_length=512)
        schema.add_field(field_name="updated_at", datatype=DataType.VARCHAR, max_length=64)
        schema.add_field(field_name="source_id", datatype=DataType.VARCHAR, max_length=512)
        schema.add_field(field_name="chunk_index", datatype=DataType.INT64)
        schema.add_field(field_name="content", datatype=DataType.VARCHAR, max_length=65535)
        schema.add_field(field_name="embedding", datatype=DataType.FLOAT_VECTOR, dim=self.dim)

        index_params = self.client.prepare_index_params()
        index_params.add_index(
            field_name="embedding",
            index_type="IVF_FLAT",
            metric_type="COSINE",
            params={"nlist": 128},
        )

        self.client.create_collection(
            collection_name=self.collection_name,
            schema=schema,
            index_params=index_params,
        )

    def insert_chunks(
        self,
        chunks: list[Chunk],
        embeddings: list[list[float]],
    ) -> None:
        if len(chunks) != len(embeddings):
            raise ValueError("chunks and embeddings must have same length")

        rows: list[dict[str, Any]] = []
        for chunk, vector in zip(chunks, embeddings):
            rows.append(
                {
                    "chunk_id": chunk.chunk_id,
                    "source_type": chunk.source_type,
                    "title": chunk.title,
                    "updated_at": chunk.updated_at.isoformat(),
                    "source_id": chunk.source_id,
                    "chunk_index": chunk.chunk_index,
                    "content": chunk.content,
                    "embedding": vector,
                }
            )
        self.client.insert(collection_name=self.collection_name, data=rows)
        self.client.flush(collection_name=self.collection_name)

    def search(
        self,
        query_embedding: list[float],
        top_k: int = 50,
    ) -> list[RetrievalResult]:
        results = self.client.search(
            collection_name=self.collection_name,
            data=[query_embedding],
            limit=top_k,
            output_fields=["chunk_id", "source_type", "title", "updated_at", "source_id", "content"],
        )
        retrieval_results: list[RetrievalResult] = []
        for group in results:
            for hit in group:
                entity = hit["entity"]
                retrieval_results.append(
                    RetrievalResult(
                        chunk_id=entity["chunk_id"],
                        content=entity["content"],
                        source_type=entity["source_type"],
                        title=entity["title"],
                        updated_at=entity["updated_at"],
                        source_id=entity["source_id"],
                        score=float(hit["distance"]),
                    )
                )
        return retrieval_results

    def get_all_chunks(self, batch_size: int = 1000) -> list[tuple[Chunk, list[float]]]:
        """查询当前 collection 中所有 chunk 及其向量。"""
        results: list[tuple[Chunk, list[float]]] = []
        offset = 0
        while True:
            batch = self.client.query(
                collection_name=self.collection_name,
                filter='chunk_id != ""',
                output_fields=[
                    "chunk_id",
                    "source_type",
                    "title",
                    "updated_at",
                    "source_id",
                    "chunk_index",
                    "content",
                    "embedding",
                ],
                offset=offset,
                limit=batch_size,
            )
            if not batch:
                break
            for row in batch:
                chunk = Chunk(
                    chunk_id=row["chunk_id"],
                    content=row["content"],
                    source_type=row["source_type"],
                    title=row["title"],
                    updated_at=datetime.fromisoformat(row["updated_at"]),
                    source_id=row["source_id"],
                    chunk_index=int(row["chunk_index"]),
                )
                results.append((chunk, row["embedding"]))
            if len(batch) < batch_size:
                break
            offset += batch_size
        return results
        if self.client.has_collection(collection_name=self.collection_name):
            self.client.drop_collection(collection_name=self.collection_name)
