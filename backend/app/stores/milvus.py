import re
from datetime import datetime
from typing import Any

from pymilvus import DataType, MilvusClient

from app.stages.base import Chunk, RetrievalResult

# 检索期过滤允许的标量字段白名单
FILTER_FIELD_WHITELIST = {"source_type", "title", "updated_at", "source_id"}

# Milvus boolean expression 保留关键字（大小写不敏感）
_FILTER_RESERVED_KEYWORDS = {
    "and",
    "or",
    "not",
    "in",
    "like",
    "match",
    "exists",
    "array",
    "json",
    "int",
    "float",
    "varchar",
    "bool",
    "true",
    "false",
    "null",
}

# 先移除单/双引号字符串，再提取标识符
_FILTER_STRING_RE = re.compile(r'"[^"\\]*(?:\\.[^"\\]*)*"|\'[^\'\\]*(?:\\.[^\'\\]*)*\'')
_FILTER_IDENTIFIER_RE = re.compile(r"\b[a-zA-Z_][a-zA-Z0-9_]*\b")


class MilvusFilterError(Exception):
    """过滤表达式字段白名单校验失败。"""

    def __init__(self, message: str, code: str = "INVALID_FILTER_FIELD"):
        super().__init__(message)
        self.message = message
        self.code = code


class MilvusStore:
    """Milvus 向量存储封装，使用 MilvusClient 简化 API。

    支持 IVF_FLAT / HNSW 两种索引算法，通过 index_type 参数切换。
    """

    def __init__(
        self,
        uri: str,
        collection_name: str,
        dim: int = 1536,
        index_type: str = "IVF_FLAT",
        metric_type: str = "COSINE",
    ):
        self.client = MilvusClient(uri=uri)
        self.collection_name = collection_name
        self.dim = dim
        self.index_type = index_type
        self.metric_type = metric_type

    def _prepare_index_params(self):
        """根据 index_type 生成对应索引参数。"""
        index_params = self.client.prepare_index_params()
        if self.index_type == "HNSW":
            index_params.add_index(
                field_name="embedding",
                index_type="HNSW",
                metric_type=self.metric_type,
                params={"M": 16, "efConstruction": 200},
            )
        elif self.index_type == "IVF_FLAT":
            index_params.add_index(
                field_name="embedding",
                index_type="IVF_FLAT",
                metric_type=self.metric_type,
                params={"nlist": 128},
            )
        else:
            raise ValueError(f"不支持的 Milvus 索引类型: {self.index_type}")
        return index_params

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

        self.client.create_collection(
            collection_name=self.collection_name,
            schema=schema,
            index_params=self._prepare_index_params(),
        )

    def insert_chunks(
        self,
        chunks: list[Chunk],
        embeddings: list[list[float]],
    ) -> None:
        if len(chunks) != len(embeddings):
            raise ValueError("chunks and embeddings must have same length")

        if embeddings and len(embeddings[0]) != self.dim:
            raise ValueError(
                f"向量维度({len(embeddings[0])})与集合维度({self.dim})不一致，"
                "请检查 embedding_dim 配置是否与 embedding 模型实际输出维度一致"
            )

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

    @staticmethod
    def _validate_filter(filter_expr: str | None) -> str | None:
        """校验过滤表达式中的字段均在白名单内。

        返回原表达式（去除首尾空格），若为空或 None 则返回 None。
        """
        if filter_expr is None:
            return None
        expr = filter_expr.strip()
        if not expr:
            return None

        cleaned = _FILTER_STRING_RE.sub("", expr)
        for identifier in _FILTER_IDENTIFIER_RE.findall(cleaned):
            lower = identifier.lower()
            if lower in _FILTER_RESERVED_KEYWORDS or identifier in FILTER_FIELD_WHITELIST:
                continue
            raise MilvusFilterError(
                f"过滤字段 '{identifier}' 不在允许的白名单内，"
                f"仅支持: {', '.join(sorted(FILTER_FIELD_WHITELIST))}"
            )
        return expr

    def search(
        self,
        query_embedding: list[float],
        top_k: int = 50,
        filter: str | None = None,
    ) -> list[RetrievalResult]:
        search_params: dict[str, Any] = {
            "collection_name": self.collection_name,
            "data": [query_embedding],
            "limit": top_k,
            "output_fields": ["chunk_id", "source_type", "title", "updated_at", "source_id", "content"],
        }
        validated_filter = self._validate_filter(filter)
        if validated_filter is not None:
            search_params["filter"] = validated_filter

        results = self.client.search(**search_params)
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
