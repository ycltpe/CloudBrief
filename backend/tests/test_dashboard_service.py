from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from app.models.schemas import (
    DashboardEvalScores,
    DashboardGraphRagStatus,
    DashboardIndexStatus,
    DashboardRecentTask,
    DashboardSystemHealth,
)
from app.services.dashboard_service import DashboardService


@pytest.fixture
def service():
    index_metadata_store = MagicMock()
    index_metadata_store.get_active.return_value = MagicMock(
        collection_name="cloudbrief_chunks_v1",
        bm25_index_path="/tmp/bm25.pkl",
    )

    celery_app = MagicMock()
    inspect = MagicMock()
    inspect.ping.return_value = {"worker@host": {"ok": "pong"}}
    celery_app.control.inspect.return_value = inspect

    return DashboardService(
        user_store=MagicMock(),
        conversation_store=MagicMock(),
        eval_store=MagicMock(),
        index_metadata_store=index_metadata_store,
        index_service=MagicMock(),
        graph_schema_store=MagicMock(),
        celery_app_instance=celery_app,
    )


@pytest.fixture
def graph_store():
    gs = MagicMock()
    gs.is_available = True
    return gs


def _dependency_names(health: DashboardSystemHealth):
    return [d.name for d in health.dependencies]


def test_system_health_all_healthy(service, graph_store):
    with patch("app.services.dashboard_service.get_engine") as mock_engine, \
         patch("app.services.dashboard_service.redis.from_url") as mock_redis, \
         patch("app.services.dashboard_service.MilvusClient") as mock_milvus:

        mock_conn = MagicMock()
        mock_engine.return_value.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.return_value.connect.return_value.__exit__ = MagicMock(return_value=False)

        mock_redis_client = MagicMock()
        mock_redis_client.ping.return_value = True
        mock_redis.return_value = mock_redis_client

        mock_milvus_client = MagicMock()
        mock_milvus_client.list_collections.return_value = ["c1"]
        mock_milvus.return_value = mock_milvus_client

        health = service._safe_system_health(graph_store)

    assert health.status == "healthy"
    assert set(_dependency_names(health)) == {
        "MySQL", "Redis", "Milvus", "Neo4j", "Celery Workers", "Index Readiness"
    }
    for dep in health.dependencies:
        assert dep.status == "healthy"
        assert dep.latency_ms is not None


def test_system_health_unhealthy_when_mysql_fails(service, graph_store):
    with patch("app.services.dashboard_service.get_engine") as mock_engine, \
         patch("app.services.dashboard_service.redis.from_url") as mock_redis, \
         patch("app.services.dashboard_service.MilvusClient") as mock_milvus:

        mock_engine.side_effect = RuntimeError("mysql connection refused")

        mock_redis_client = MagicMock()
        mock_redis_client.ping.return_value = True
        mock_redis.return_value = mock_redis_client

        mock_milvus_client = MagicMock()
        mock_milvus_client.list_collections.return_value = ["c1"]
        mock_milvus.return_value = mock_milvus_client

        health = service._safe_system_health(graph_store)

    assert health.status == "unhealthy"
    mysql_dep = next(d for d in health.dependencies if d.name == "MySQL")
    assert mysql_dep.status == "unhealthy"
    assert "mysql connection refused" in mysql_dep.message


def test_system_health_degraded_when_neo4j_unavailable(service):
    with patch("app.services.dashboard_service.get_engine") as mock_engine, \
         patch("app.services.dashboard_service.redis.from_url") as mock_redis, \
         patch("app.services.dashboard_service.MilvusClient") as mock_milvus:

        mock_conn = MagicMock()
        mock_engine.return_value.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.return_value.connect.return_value.__exit__ = MagicMock(return_value=False)

        mock_redis_client = MagicMock()
        mock_redis_client.ping.return_value = True
        mock_redis.return_value = mock_redis_client

        mock_milvus_client = MagicMock()
        mock_milvus_client.list_collections.return_value = ["c1"]
        mock_milvus.return_value = mock_milvus_client

        graph_store = MagicMock()
        graph_store.is_available = False

        health = service._safe_system_health(graph_store)

    assert health.status == "degraded"
    neo4j_dep = next(d for d in health.dependencies if d.name == "Neo4j")
    assert neo4j_dep.status == "degraded"


def test_system_health_degraded_when_no_active_index(service, graph_store):
    service.index_metadata_store.get_active.return_value = None

    with patch("app.services.dashboard_service.get_engine") as mock_engine, \
         patch("app.services.dashboard_service.redis.from_url") as mock_redis, \
         patch("app.services.dashboard_service.MilvusClient") as mock_milvus:

        mock_conn = MagicMock()
        mock_engine.return_value.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.return_value.connect.return_value.__exit__ = MagicMock(return_value=False)

        mock_redis_client = MagicMock()
        mock_redis_client.ping.return_value = True
        mock_redis.return_value = mock_redis_client

        mock_milvus_client = MagicMock()
        mock_milvus_client.list_collections.return_value = ["c1"]
        mock_milvus.return_value = mock_milvus_client

        health = service._safe_system_health(graph_store)

    assert health.status == "degraded"
    index_dep = next(d for d in health.dependencies if d.name == "Index Readiness")
    assert index_dep.status == "degraded"
    assert "无活跃索引" in index_dep.message


def test_system_health_celery_workers_unhealthy_when_no_workers(service, graph_store):
    service.celery_app.control.inspect.return_value.ping.return_value = None

    with patch("app.services.dashboard_service.get_engine") as mock_engine, \
         patch("app.services.dashboard_service.redis.from_url") as mock_redis, \
         patch("app.services.dashboard_service.MilvusClient") as mock_milvus:

        mock_conn = MagicMock()
        mock_engine.return_value.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.return_value.connect.return_value.__exit__ = MagicMock(return_value=False)

        mock_redis_client = MagicMock()
        mock_redis_client.ping.return_value = True
        mock_redis.return_value = mock_redis_client

        mock_milvus_client = MagicMock()
        mock_milvus_client.list_collections.return_value = ["c1"]
        mock_milvus.return_value = mock_milvus_client

        health = service._safe_system_health(graph_store)

    assert health.status == "unhealthy"
    celery_dep = next(d for d in health.dependencies if d.name == "Celery Workers")
    assert celery_dep.status == "unhealthy"
    assert "没有可用的 Celery Worker" in celery_dep.message


def test_system_health_checked_at_isoformat(service, graph_store):
    with patch("app.services.dashboard_service.get_engine") as mock_engine, \
         patch("app.services.dashboard_service.redis.from_url") as mock_redis, \
         patch("app.services.dashboard_service.MilvusClient") as mock_milvus:

        mock_conn = MagicMock()
        mock_engine.return_value.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.return_value.connect.return_value.__exit__ = MagicMock(return_value=False)

        mock_redis_client = MagicMock()
        mock_redis_client.ping.return_value = True
        mock_redis.return_value = mock_redis_client

        mock_milvus_client = MagicMock()
        mock_milvus_client.list_collections.return_value = ["c1"]
        mock_milvus.return_value = mock_milvus_client

        health = service._safe_system_health(graph_store)

    assert health.checked_at is not None
    parsed = datetime.fromisoformat(health.checked_at)
    assert parsed.year >= 2026


def test_get_dashboard_passes_graph_store(service, graph_store):
    service.user_store.count.return_value = 1
    service.conversation_store.count_today.return_value = 2
    service.index_service.get_recent_tasks.return_value = []
    service.eval_store.get_latest_scores.return_value = {}
    service.graph_schema_store = MagicMock()
    service.graph_schema_store.list_enabled = MagicMock(return_value=[])

    with patch("app.services.dashboard_service.get_engine") as mock_engine, \
         patch("app.services.dashboard_service.redis.from_url") as mock_redis, \
         patch("app.services.dashboard_service.MilvusClient") as mock_milvus:

        mock_conn = MagicMock()
        mock_engine.return_value.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.return_value.connect.return_value.__exit__ = MagicMock(return_value=False)

        mock_redis_client = MagicMock()
        mock_redis_client.ping.return_value = True
        mock_redis.return_value = mock_redis_client

        mock_milvus_client = MagicMock()
        mock_milvus_client.list_collections.return_value = ["c1"]
        mock_milvus.return_value = mock_milvus_client

        result = service.get_dashboard(graph_store=graph_store)

    assert result.system_health.status == "healthy"
    assert len(result.system_health.dependencies) == 6


def test_get_stats_returns_aggregated_counts(service):
    service.user_store.count.return_value = 10
    service.conversation_store.count_today.return_value = 5
    service.index_service.get_recent_tasks.return_value = []
    service.eval_store.get_latest_scores.return_value = {}

    result = service.get_stats()

    assert result.user_count == 10
    assert result.conversation_count_today == 5
    assert isinstance(result.index_status, DashboardIndexStatus)
    assert isinstance(result.latest_eval_scores, DashboardEvalScores)


def test_get_eval_scores_returns_latest_scores(service):
    service.eval_store.get_latest_scores.return_value = {
        "context_precision": 0.8,
        "context_recall": 0.75,
        "faithfulness": 0.9,
        "answer_relevancy": 0.85,
    }

    result = service.get_eval_scores()

    assert result.latest_eval_scores.context_precision == 0.8
    assert result.latest_eval_scores.context_recall == 0.75
    assert result.latest_eval_scores.faithfulness == 0.9
    assert result.latest_eval_scores.answer_relevancy == 0.85


def test_get_recent_tasks_returns_tasks(service):
    tasks = [
        DashboardRecentTask(task_id="task-1", status="completed"),
        DashboardRecentTask(task_id="task-2", status="running"),
    ]
    service.index_service.get_recent_tasks.return_value = tasks

    result = service.get_recent_tasks()

    assert result.recent_tasks == tasks


def test_get_graph_rag_status_returns_default_on_failure(service):
    service.graph_schema_store = MagicMock()
    service.graph_schema_store.list_enabled.side_effect = RuntimeError("db error")

    result = service.get_graph_rag_status()

    assert isinstance(result.graph_rag_status, DashboardGraphRagStatus)


def test_get_system_health_healthy(service, graph_store):
    with patch("app.services.dashboard_service.get_engine") as mock_engine, \
         patch("app.services.dashboard_service.redis.from_url") as mock_redis, \
         patch("app.services.dashboard_service.MilvusClient") as mock_milvus:

        mock_conn = MagicMock()
        mock_engine.return_value.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.return_value.connect.return_value.__exit__ = MagicMock(return_value=False)

        mock_redis_client = MagicMock()
        mock_redis_client.ping.return_value = True
        mock_redis.return_value = mock_redis_client

        mock_milvus_client = MagicMock()
        mock_milvus_client.list_collections.return_value = ["c1"]
        mock_milvus.return_value = mock_milvus_client

        result = service.get_system_health(graph_store=graph_store)

    assert result.system_health.status == "healthy"
    assert len(result.system_health.dependencies) == 6
