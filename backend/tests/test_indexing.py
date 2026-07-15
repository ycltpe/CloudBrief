from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from app.stages.base import Chunk, Document, EmbeddingResult
from app.tasks.indexing import index_file_task, rebuild_index_task


def _make_kb_file(file_id: int = 1):
    file = MagicMock()
    file.id = file_id
    file.directory_id = 1
    file.original_name = "test.md"
    file.relative_path = "dir_1/test_abc.md"
    return file


def _make_document():
    return Document(
        content="hello world",
        source_type="kb_doc",
        title="test",
        updated_at=datetime.utcnow(),
        source_id="dir_1/test_abc.md",
    )


def _make_chunk(chunk_id: str, source_id: str = "dir_1/test_abc.md"):
    return Chunk(
        chunk_id=chunk_id,
        content="hello",
        source_type="kb_doc",
        title="test",
        updated_at=datetime.utcnow(),
        source_id=source_id,
        chunk_index=0,
    )


def _make_embedding(chunk_id: str, dim: int = 3):
    return EmbeddingResult(chunk_id=chunk_id, embedding=[0.1] * dim)


class _FakeNativeParser:
    def __init__(self, data_dir):
        pass

    def parse_file(self, file_path, on_progress=None):
        return [_make_document()]


class _FakeChunkingStage:
    def __init__(self, *args, **kwargs):
        pass

    def execute(self, input_data):
        return MagicMock(chunks=[_make_chunk("new_chunk", source_id="dir_1/test_abc.md")])


class _FakeEmbeddingStage:
    def __init__(self, *args, **kwargs):
        pass

    def execute(self, input_data, model_name=None, on_progress=None):
        return MagicMock(embeddings=[_make_embedding("new_chunk", dim=3)])


class _FakeMilvusStore:
    def __init__(self, existing=None):
        self.existing = existing or []
        self.inserted_chunks = None
        self.inserted_embeddings = None

    def get_all_chunks(self):
        return self.existing

    def create_collection(self):
        pass

    def insert_chunks(self, chunks, embeddings):
        self.inserted_chunks = chunks
        self.inserted_embeddings = embeddings


class _FakeBM25Store:
    def __init__(self, path):
        self.path = path
        self.built_chunks = None

    def build_index(self, chunks):
        self.built_chunks = chunks

    def save(self):
        pass


@pytest.fixture
def patched_indexing_env(tmp_path, monkeypatch):
    """为 index_file_task 提供全 mock 运行环境。"""
    storage = tmp_path / "kb"
    storage.mkdir()
    (storage / "dir_1").mkdir()
    (storage / "dir_1" / "test_abc.md").write_text("# Hello", encoding="utf-8")

    settings = MagicMock()
    settings.kb_storage_path = storage
    settings.milvus_collection = "cloudbrief_chunks"
    settings.bm25_index_path = tmp_path / "bm25.pkl"
    settings.milvus_uri = "http://localhost:19531"
    settings.redis_url = "redis://localhost:6381/0"
    settings.embedding_model = "text-embedding-v3"
    settings.embedding_dim = 3

    fake_file = _make_kb_file()
    kb_store = MagicMock()
    kb_store.get_file.return_value = fake_file
    kb_store.get_root_directory_id.return_value = 1

    metadata_store = MagicMock()
    metadata_store.get_active.return_value = MagicMock(collection_name="active_coll")

    graph_schema_store = MagicMock()
    graph_schema_store.get_by_directory_id.return_value = None

    settings_service = MagicMock()
    settings_service.get_runtime_value.side_effect = lambda key: {
        "embedding_model": settings.embedding_model,
        "embedding_dim": settings.embedding_dim,
    }.get(key)

    patches = [
        patch("app.tasks.indexing.get_settings", return_value=settings),
        patch("app.tasks.indexing._get_redis_client", return_value=MagicMock()),
        patch("app.tasks.indexing._publish_step"),
        patch(
            "app.tasks.indexing.build_parser",
            lambda settings, data_dir, model_client=None: _FakeNativeParser(data_dir),
        ),
        patch("app.tasks.indexing.ChunkingStage", _FakeChunkingStage),
        patch("app.tasks.indexing.EmbeddingStage", _FakeEmbeddingStage),
        patch("app.tasks.indexing.KbStore", return_value=kb_store),
        patch("app.tasks.indexing.IndexMetadataStore", return_value=metadata_store),
        patch("app.stores.graph_schema_store.GraphSchemaStore", return_value=graph_schema_store),
        patch("app.tasks.indexing.SettingsService", return_value=settings_service),
        patch("app.tasks.indexing.ModelClient"),
    ]

    for p in patches:
        p.start()

    # MilvusStore / BM25Store 需要在测试里单独控制，这里先 patch 成通用工厂
    milvus_patcher = patch("app.tasks.indexing.MilvusStore")
    bm25_patcher = patch("app.tasks.indexing.BM25Store")
    milvus_mock_cls = milvus_patcher.start()
    bm25_mock_cls = bm25_patcher.start()

    yield {
        "settings": settings,
        "kb_store": kb_store,
        "metadata_store": metadata_store,
        "milvus_mock_cls": milvus_mock_cls,
        "bm25_mock_cls": bm25_mock_cls,
    }

    milvus_patcher.stop()
    bm25_patcher.stop()
    for p in reversed(patches):
        p.stop()


def test_index_file_task_merges_new_chunks_with_existing(patched_indexing_env):
    existing_chunk = _make_chunk("existing_chunk", source_id="old_doc.md")
    fake_store = _FakeMilvusStore(existing=[(existing_chunk, [0.0, 0.0, 0.0])])
    patched_indexing_env["milvus_mock_cls"].return_value = fake_store
    patched_indexing_env["bm25_mock_cls"].side_effect = _FakeBM25Store

    index_file_task.run(file_id=1)

    assert fake_store.inserted_chunks is not None
    source_ids = {c.source_id for c in fake_store.inserted_chunks}
    assert source_ids == {"old_doc.md", "dir_1/test_abc.md"}


def test_index_file_task_replaces_existing_same_source_id(patched_indexing_env):
    existing_chunk = _make_chunk("existing_chunk", source_id="dir_1/test_abc.md")
    fake_store = _FakeMilvusStore(existing=[(existing_chunk, [0.0, 0.0, 0.0])])
    patched_indexing_env["milvus_mock_cls"].return_value = fake_store
    patched_indexing_env["bm25_mock_cls"].side_effect = _FakeBM25Store

    index_file_task.run(file_id=1)

    chunks = fake_store.inserted_chunks
    assert len(chunks) == 1
    assert chunks[0].chunk_id == "new_chunk"


def test_index_file_task_fails_on_dimension_mismatch(patched_indexing_env):
    existing_chunk = _make_chunk("existing_chunk", source_id="old_doc.md")
    fake_store = _FakeMilvusStore(existing=[(existing_chunk, [0.0, 0.0])])  # dim=2
    patched_indexing_env["milvus_mock_cls"].return_value = fake_store
    patched_indexing_env["bm25_mock_cls"].side_effect = _FakeBM25Store

    with pytest.raises(ValueError, match="活跃索引维度"):
        index_file_task.run(file_id=1)

    kb_store = patched_indexing_env["kb_store"]
    calls = kb_store.update_file_index_status.call_args_list
    assert len(calls) >= 2
    last = calls[-1]
    assert last.args[1] == "failed"
    assert last.kwargs["index_error"] is not None


def test_index_file_task_marks_failed_when_parse_raises(patched_indexing_env):
    patched_indexing_env["milvus_mock_cls"].return_value = _FakeMilvusStore()
    patched_indexing_env["bm25_mock_cls"].side_effect = _FakeBM25Store

    with patch("app.tasks.indexing.build_parser") as build_parser_mock:
        build_parser_mock.return_value.parse_file.side_effect = ValueError("bad file")
        with pytest.raises(ValueError, match="bad file"):
            index_file_task.run(file_id=1)

    kb_store = patched_indexing_env["kb_store"]
    calls = kb_store.update_file_index_status.call_args_list
    assert len(calls) >= 2
    last = calls[-1]
    assert last.args[1] == "failed"


def test_rebuild_task_aborts_when_no_documents():
    """全灭重建（所有文件解析失败）必须中止，不得切换空索引上线。"""
    with (
        patch("app.tasks.indexing._get_redis_client"),
        patch("app.tasks.indexing.ModelClient"),
        patch("app.tasks.indexing.SettingsService") as settings_service_cls,
        patch(
            "app.tasks.indexing._parse_documents",
            return_value=([], ["scanned.pdf: 该 PDF 无文字层（可能是扫描件），本期暂不支持"]),
        ),
        patch("app.tasks.indexing.MilvusStore") as milvus_cls,
        patch("app.tasks.indexing.IndexMetadataStore") as metadata_cls,
    ):
        settings_service_cls.return_value.get_runtime_value.side_effect = ["model-x", 1024]
        with pytest.raises(ValueError, match="未解析到任何有效文档"):
            rebuild_index_task.run(kb_id="default")
        milvus_cls.assert_not_called()
        metadata_cls.assert_not_called()
