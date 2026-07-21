"""QueryLogStore 单元测试：覆盖 extra_json 写入与读取反序列化。"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.stores.db import Base, QueryLog
from app.stores.query_log import QueryLogStore


@pytest.fixture
def session_factory():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture
def store(session_factory):
    return QueryLogStore(session_factory=session_factory)


@pytest.fixture
def retrieval_metadata():
    return {
        "vector_hits": 10,
        "bm25_hits": 5,
        "rrf_k": 60,
        "rerank_provider": "dashscope",
        "applied_filter": 'updated_at >= "2026-01-01T00:00:00"',
        "index_version": "test_collection_v1",
        "index_type": "IVF_FLAT",
    }


class TestQueryLogStore:
    """QueryLogStore.insert 写入与反序列化测试。"""

    def test_insert_stores_retrieval_metadata(
        self, store, session_factory, retrieval_metadata
    ):
        log = store.insert(
            user_id=1,
            received_at=__import__("datetime").datetime.utcnow(),
            original_question="测试问题",
            rewritten_question="改写后的问题",
            kb_id="default",
            question_type=None,
            config_snapshot={"k": "v"},
            retrieval_adapter="native",
            is_fallback=False,
            max_score=0.9,
            retrieved_chunks=[],
            answer="测试答案",
            citations=[],
            is_refusal=False,
            is_stale=False,
            graphrag_enabled=False,
            graphrag_used=False,
            latency_ms_rewrite=10,
            latency_ms_retrieve=20,
            latency_ms_generate=30,
            latency_ms_total=60,
            retrieval_metadata=retrieval_metadata,
        )

        assert log.id is not None
        assert log.extra_json == retrieval_metadata

        with session_factory() as session:
            row = session.query(QueryLog).filter_by(id=log.id).first()
            assert row.extra_json == retrieval_metadata

    def test_insert_without_metadata_defaults_to_empty_dict(self, store, session_factory):
        log = store.insert(
            user_id=1,
            received_at=__import__("datetime").datetime.utcnow(),
            original_question="测试问题",
            rewritten_question=None,
            kb_id="default",
            question_type=None,
            config_snapshot={},
            retrieval_adapter="native",
            is_fallback=False,
            max_score=None,
            retrieved_chunks=[],
            answer=None,
            citations=[],
            is_refusal=True,
            is_stale=False,
            graphrag_enabled=False,
            graphrag_used=False,
            latency_ms_rewrite=None,
            latency_ms_retrieve=None,
            latency_ms_generate=None,
            latency_ms_total=None,
        )

        assert log.extra_json == {}

        with session_factory() as session:
            row = session.query(QueryLog).filter_by(id=log.id).first()
            assert row.extra_json == {}

    def test_legacy_row_with_null_extra_json_deserializes_safely(
        self, store, session_factory
    ):
        from datetime import datetime

        with session_factory() as session:
            legacy = QueryLog(
                log_hash="legacy_hash",
                user_hash="user_hash",
                received_at=datetime.utcnow(),
                original_question="旧数据",
                rewritten_question=None,
                kb_id="default",
                question_type=None,
                config_snapshot="{}",
                retrieval_adapter="native",
                is_fallback=False,
                max_score=None,
                retrieved_chunks="[]",
                answer=None,
                citations_json="[]",
                is_refusal=False,
                is_stale=False,
                graphrag_enabled=False,
                graphrag_used=False,
                latency_ms_rewrite=None,
                latency_ms_retrieve=None,
                latency_ms_generate=None,
                latency_ms_total=None,
                extra_json=None,
            )
            session.add(legacy)
            session.commit()
            session.refresh(legacy)

        with session_factory() as session:
            row = session.query(QueryLog).filter_by(id=legacy.id).first()
            assert row.extra_json is None
