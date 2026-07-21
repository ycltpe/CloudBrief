"""RetrievalPipeline 单元测试：覆盖检索期时效过滤与空结果路径。"""

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.pipelines.retrieval import RetrievalPipeline
from app.stages.base import RetrievalResult


@pytest.fixture
def pipeline():
    model_client = MagicMock()
    pipeline = RetrievalPipeline(model_client)
    pipeline.settings_service.get_runtime_value = MagicMock(
        side_effect=lambda key: {
            "retrieval_adapter": "native",
            "orchestration_mode": "native",
            "stale_threshold_days": 90,
            "embedding_model": "text-embedding-v3",
            "milvus_uri": "http://localhost:19531",
        }.get(key)
    )
    return pipeline


def _make_result(chunk_id: str, updated_at: datetime | str, score: float = 0.5) -> RetrievalResult:
    return RetrievalResult(
        chunk_id=chunk_id,
        content="content",
        source_type="help_doc",
        title="title",
        updated_at=updated_at,
        source_id="s.md",
        score=score,
    )


@pytest.fixture
def active_index():
    return SimpleNamespace(
        collection_name="test_collection",
        bm25_index_path="/tmp/bm25.pkl",
    )


@pytest.fixture
def stage_mocks(pipeline, active_index):
    """统一 mock 检索管线的 store 与 stage。"""
    with patch.object(pipeline.index_metadata_store, "get_active", return_value=active_index), \
            patch("app.pipelines.retrieval.MilvusStore") as _milvus, \
            patch("app.pipelines.retrieval.BM25Store") as mock_bm25, \
            patch("app.pipelines.retrieval.VectorRetrievalStage") as mock_vector_cls, \
            patch("app.pipelines.retrieval.BM25RetrievalStage") as mock_bm25_cls, \
            patch("app.pipelines.retrieval.HybridFusionStage") as mock_fusion_cls, \
            patch("app.pipelines.retrieval.create_reranker_adapter") as _create_reranker, \
            patch("app.pipelines.retrieval.RerankingStage") as mock_rerank_cls:
        mock_bm25.return_value.load = MagicMock()

        def _set_vector_results(results, is_fallback=False):
            mock_vector_cls.return_value.execute.return_value = MagicMock(results=results)

        def _set_bm25_results(results):
            mock_bm25_cls.return_value.execute.return_value = MagicMock(results=results)

        def _set_fusion_results(results):
            mock_fusion_cls.return_value.execute.return_value = MagicMock(fused_results=results)

        def _set_rerank_results(results, is_fallback=False):
            mock_rerank_cls.return_value.execute.return_value = MagicMock(
                reranked_results=results,
                is_fallback=is_fallback,
            )

        yield SimpleNamespace(
            vector_cls=mock_vector_cls,
            bm25_cls=mock_bm25_cls,
            fusion_cls=mock_fusion_cls,
            rerank_cls=mock_rerank_cls,
            set_vector_results=_set_vector_results,
            set_bm25_results=_set_bm25_results,
            set_fusion_results=_set_fusion_results,
            set_rerank_results=_set_rerank_results,
        )


class TestFreshnessFilterHelpers:
    """时效过滤表达式与 freshness 判断辅助函数测试。"""

    def test_build_freshness_filter(self):
        expr = RetrievalPipeline._build_freshness_filter(90)
        assert expr.startswith('updated_at >= "')
        cutoff_str = expr.split('updated_at >= "')[1].rstrip('"')
        cutoff = datetime.fromisoformat(cutoff_str)
        expected = datetime.utcnow() - timedelta(days=90)
        assert abs((cutoff - expected).total_seconds()) < 1

    @pytest.mark.parametrize("threshold", [0, -1])
    def test_build_freshness_filter_non_positive_returns_none(self, threshold):
        assert RetrievalPipeline._build_freshness_filter(threshold) is None

    def test_is_fresh_with_datetime(self):
        cutoff = datetime.utcnow() - timedelta(days=90)
        fresh = _make_result("c1", datetime.utcnow())
        stale = _make_result("c2", datetime.utcnow() - timedelta(days=91))
        assert RetrievalPipeline._is_fresh(fresh, cutoff) is True
        assert RetrievalPipeline._is_fresh(stale, cutoff) is False

    def test_is_fresh_with_iso_string(self):
        cutoff = datetime.utcnow() - timedelta(days=90)
        fresh = _make_result("c1", (datetime.utcnow() - timedelta(days=1)).isoformat())
        stale = _make_result("c2", (datetime.utcnow() - timedelta(days=91)).isoformat())
        assert RetrievalPipeline._is_fresh(fresh, cutoff) is True
        assert RetrievalPipeline._is_fresh(stale, cutoff) is False

    def test_is_fresh_invalid_string_treated_as_fresh(self):
        cutoff = datetime.utcnow() - timedelta(days=90)
        result = SimpleNamespace(updated_at="not-a-date")
        assert RetrievalPipeline._is_fresh(result, cutoff) is True


class TestRetrieveWithFreshnessFilter:
    """RetrievalPipeline.retrieve 检索期时效过滤集成测试。"""

    def test_vector_stage_receives_freshness_filter(self, pipeline, stage_mocks):
        stage_mocks.set_vector_results([])
        stage_mocks.set_bm25_results([])
        stage_mocks.set_fusion_results([])
        stage_mocks.set_rerank_results([])

        pipeline.retrieve("query", top_k=10, top_n=3, kb_id="default")

        vector_execute = stage_mocks.vector_cls.return_value.execute
        assert vector_execute.called
        input_data = vector_execute.call_args.args[0]
        assert input_data.filter.startswith('updated_at >= "')

    def test_fresh_results_preserved_and_stale_filtered(self, pipeline, stage_mocks):
        fresh_vec = _make_result("fresh_vec", datetime.utcnow() - timedelta(days=1), score=0.9)
        stale_vec = _make_result("stale_vec", datetime.utcnow() - timedelta(days=91), score=0.8)
        stale_bm25 = _make_result("stale_bm25", datetime.utcnow() - timedelta(days=120), score=0.7)

        stage_mocks.set_vector_results([fresh_vec, stale_vec])
        stage_mocks.set_bm25_results([stale_bm25])
        stage_mocks.set_fusion_results([fresh_vec, stale_vec, stale_bm25])
        stage_mocks.set_rerank_results([fresh_vec, stale_vec, stale_bm25])

        output = pipeline.retrieve("query", top_k=10, top_n=3, kb_id="default")

        assert len(output.results) == 1
        assert output.results[0].chunk_id == "fresh_vec"
        assert output.is_fallback is False

    def test_all_stale_results_return_empty(self, pipeline, stage_mocks):
        stale = _make_result("stale", datetime.utcnow() - timedelta(days=100), score=0.9)
        stage_mocks.set_vector_results([stale])
        stage_mocks.set_bm25_results([])
        stage_mocks.set_fusion_results([stale])
        stage_mocks.set_rerank_results([stale])

        output = pipeline.retrieve("query", top_k=10, top_n=3, kb_id="default")

        assert output.results == []

    def test_vector_failure_with_stale_bm25_returns_empty(self, pipeline, stage_mocks):
        stale_bm25 = _make_result("stale_bm25", datetime.utcnow() - timedelta(days=100), score=0.9)

        stage_mocks.vector_cls.return_value.execute.side_effect = RuntimeError("milvus down")
        stage_mocks.set_bm25_results([stale_bm25])
        stage_mocks.set_fusion_results([stale_bm25])
        stage_mocks.set_rerank_results([stale_bm25])

        output = pipeline.retrieve("query", top_k=10, top_n=3, kb_id="default")

        assert output.results == []
        assert output.is_fallback is True

    def test_rerank_fallback_flag_preserved(self, pipeline, stage_mocks):
        fresh = _make_result("fresh", datetime.utcnow() - timedelta(days=1), score=0.9)
        stage_mocks.set_vector_results([fresh])
        stage_mocks.set_bm25_results([])
        stage_mocks.set_fusion_results([fresh])
        stage_mocks.set_rerank_results([fresh], is_fallback=True)

        output = pipeline.retrieve("query", top_k=10, top_n=3, kb_id="default")

        assert output.is_fallback is True
        assert len(output.results) == 1


class TestFilterCombination:
    """外部 filter（Self-Querying）与 freshness filter 的合并。"""

    def test_combine_filters_all_none_returns_none(self):
        assert RetrievalPipeline._combine_filters(None, None) is None
        assert RetrievalPipeline._combine_filters(None, "", None) is None

    def test_combine_filters_single_part_unchanged(self):
        assert RetrievalPipeline._combine_filters('a == "b"') == 'a == "b"'
        assert RetrievalPipeline._combine_filters(None, 'a == "b"') == 'a == "b"'

    def test_combine_filters_joins_with_and(self):
        combined = RetrievalPipeline._combine_filters('a == "b"', 'c >= "d"')
        assert combined == '(a == "b") AND (c >= "d")'

    def test_retrieve_combines_self_querying_and_freshness_filters(self, pipeline, stage_mocks):
        stage_mocks.set_vector_results([])
        stage_mocks.set_bm25_results([])
        stage_mocks.set_fusion_results([])
        stage_mocks.set_rerank_results([])

        external_filter = 'source_type == "changelog"'
        pipeline.retrieve(
            "query", top_k=10, top_n=3, kb_id="default", filter=external_filter
        )

        vector_execute = stage_mocks.vector_cls.return_value.execute
        input_data = vector_execute.call_args.args[0]
        assert input_data.filter.startswith('(updated_at >= "')
        assert 'source_type == "changelog"' in input_data.filter
        assert " AND " in input_data.filter
