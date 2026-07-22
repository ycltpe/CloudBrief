from datetime import datetime
from unittest.mock import patch

import pytest

from app.stages.base import Chunk
from app.stores.milvus import FILTER_FIELD_WHITELIST, MilvusFilterError, MilvusStore


@pytest.fixture
def mock_milvus_client():
    with patch("app.stores.milvus.MilvusClient") as mock_cls:
        yield mock_cls


@pytest.fixture
def store(mock_milvus_client):
    return MilvusStore(uri="http://localhost:19531", collection_name="test_collection", dim=4)


def _make_search_result(**overrides):
    return {
        "entity": {
            "chunk_id": overrides.get("chunk_id", "chunk_1"),
            "source_type": overrides.get("source_type", "help_doc"),
            "title": overrides.get("title", "test title"),
            "updated_at": overrides.get("updated_at", datetime.utcnow().isoformat()),
            "source_id": overrides.get("source_id", "help/test.md"),
            "content": overrides.get("content", "test content"),
        },
        "distance": 0.9,
    }


class TestMilvusStoreSearchFilter:
    """MilvusStore.search filter 参数单元测试。"""

    def test_search_without_filter_does_not_pass_filter(self, store, mock_milvus_client):
        mock_client = mock_milvus_client.return_value
        mock_client.search.return_value = [[_make_search_result()]]

        results = store.search(query_embedding=[0.1, 0.2, 0.3, 0.4], top_k=10)

        assert len(results) == 1
        call_kwargs = mock_client.search.call_args.kwargs
        assert "filter" not in call_kwargs
        assert call_kwargs["collection_name"] == "test_collection"
        assert call_kwargs["limit"] == 10

    def test_search_with_none_filter_keeps_existing_behavior(self, store, mock_milvus_client):
        mock_client = mock_milvus_client.return_value
        mock_client.search.return_value = [[_make_search_result()]]

        results = store.search(query_embedding=[0.1, 0.2, 0.3, 0.4], filter=None)

        assert len(results) == 1
        assert "filter" not in mock_client.search.call_args.kwargs

    @pytest.mark.parametrize("empty_filter", ["", "   ", "\t\n"])
    def test_search_with_empty_filter_treated_as_no_filter(self, store, mock_milvus_client, empty_filter):
        mock_client = mock_milvus_client.return_value
        mock_client.search.return_value = [[_make_search_result()]]

        results = store.search(query_embedding=[0.1, 0.2, 0.3, 0.4], filter=empty_filter)

        assert len(results) == 1
        assert "filter" not in mock_client.search.call_args.kwargs

    def test_search_with_valid_filter_passes_to_client(self, store, mock_milvus_client):
        mock_client = mock_milvus_client.return_value
        mock_client.search.return_value = [[_make_search_result()]]
        filter_expr = 'source_type == "help_doc" AND updated_at >= "2024-01-01"'

        results = store.search(
            query_embedding=[0.1, 0.2, 0.3, 0.4],
            top_k=20,
            filter=filter_expr,
        )

        assert len(results) == 1
        call_kwargs = mock_client.search.call_args.kwargs
        assert call_kwargs["filter"] == filter_expr
        assert call_kwargs["limit"] == 20

    @pytest.mark.parametrize(
        "valid_filter",
        [
            'source_type == "help_doc"',
            'title LIKE "%导出%"',
            'source_id IN ["a.md", "b.md"]',
            'updated_at >= "2024-01-01" OR source_type == "changelog"',
            'source_type != "faq" AND updated_at < "2025-01-01"',
        ],
    )
    def test_valid_filters_accepted(self, store, mock_milvus_client, valid_filter):
        mock_client = mock_milvus_client.return_value
        mock_client.search.return_value = [[_make_search_result()]]

        store.search(query_embedding=[0.1, 0.2, 0.3, 0.4], filter=valid_filter)

        assert mock_client.search.call_args.kwargs["filter"] == valid_filter

    @pytest.mark.parametrize(
        "invalid_filter, invalid_field",
        [
            ('tenant_id == "abc"', "tenant_id"),
            ('source_type == "help_doc" AND kb_id == "default"', "kb_id"),
            ('owner == "admin" OR updated_at > "2024-01-01"', "owner"),
            ('content == "secret"', "content"),
            ('embedding == [0.1]', "embedding"),
        ],
    )
    def test_invalid_filter_field_raises(self, store, invalid_filter, invalid_field):
        with pytest.raises(MilvusFilterError) as exc_info:
            store.search(query_embedding=[0.1, 0.2, 0.3, 0.4], filter=invalid_filter)

        assert exc_info.value.code == "INVALID_FILTER_FIELD"
        assert invalid_field in exc_info.value.message
        assert all(field in exc_info.value.message for field in FILTER_FIELD_WHITELIST)

    def test_filter_string_literals_not_treated_as_fields(self, store, mock_milvus_client):
        """字符串字面量中的内容不应被误判为字段名。"""
        mock_client = mock_milvus_client.return_value
        mock_client.search.return_value = [[_make_search_result()]]
        filter_expr = 'title == "content" AND source_type == "embedding"'

        store.search(query_embedding=[0.1, 0.2, 0.3, 0.4], filter=filter_expr)

        assert mock_client.search.call_args.kwargs["filter"] == filter_expr


class TestMilvusStoreInsert:
    """MilvusStore 写入相关测试。"""

    def test_insert_chunks_dimension_mismatch_raises(self, store):
        chunk = Chunk(
            chunk_id="c1",
            content="hello",
            source_type="help_doc",
            title="t",
            updated_at=datetime.utcnow(),
            source_id="s.md",
            chunk_index=0,
        )

        with pytest.raises(ValueError, match="向量维度"):
            store.insert_chunks([chunk], embeddings=[[0.1, 0.2, 0.3]])

    def test_insert_chunks_length_mismatch_raises(self, store):
        chunk = Chunk(
            chunk_id="c1",
            content="hello",
            source_type="help_doc",
            title="t",
            updated_at=datetime.utcnow(),
            source_id="s.md",
            chunk_index=0,
        )

        with pytest.raises(ValueError, match="same length"):
            store.insert_chunks([chunk, chunk], embeddings=[[0.1, 0.2, 0.3, 0.4]])


class TestMilvusStoreIndexType:
    """MilvusStore 索引算法参数测试。"""

    def test_default_index_type_is_ivf_flat(self, mock_milvus_client):
        store = MilvusStore(uri="http://localhost:19531", collection_name="test_collection", dim=4)
        assert store.index_type == "IVF_FLAT"

    def test_hnsw_index_creation_uses_hnsw_params(self, mock_milvus_client):
        store = MilvusStore(
            uri="http://localhost:19531",
            collection_name="test_hnsw",
            dim=4,
            index_type="HNSW",
            metric_type="COSINE",
        )
        store.create_collection()

        mock_client = mock_milvus_client.return_value
        index_params = mock_client.create_collection.call_args.kwargs["index_params"]
        index_params.add_index.assert_called_once()
        call_kwargs = index_params.add_index.call_args.kwargs
        assert call_kwargs["index_type"] == "HNSW"
        assert call_kwargs["metric_type"] == "COSINE"
        assert call_kwargs["params"] == {"M": 16, "efConstruction": 200}

    def test_unsupported_index_type_raises(self, mock_milvus_client):
        store = MilvusStore(
            uri="http://localhost:19531",
            collection_name="test_unknown",
            dim=4,
            index_type="UNKNOWN",
        )
        with pytest.raises(ValueError, match="不支持的 Milvus 索引类型"):
            store.create_collection()


class TestMilvusFilterError:
    """MilvusFilterError 异常结构测试。"""

    def test_error_code_and_message(self):
        exc = MilvusFilterError("bad field")

        assert exc.code == "INVALID_FILTER_FIELD"
        assert exc.message == "bad field"
        assert str(exc) == "bad field"

    def test_custom_code(self):
        exc = MilvusFilterError("other", code="OTHER_CODE")

        assert exc.code == "OTHER_CODE"
