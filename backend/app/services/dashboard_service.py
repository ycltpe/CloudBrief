from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from time import perf_counter
from typing import Any

import redis
import structlog
from pymilvus import MilvusClient
from sqlalchemy import text

from app.celery_app import celery_app
from app.config import get_settings
from app.models.schemas import (
    AdminDashboardResponse,
    DashboardDependencyStatus,
    DashboardEvalScores,
    DashboardEvalScoresResponse,
    DashboardGraphRagResponse,
    DashboardGraphRagStatus,
    DashboardIndexStatus,
    DashboardRecentTask,
    DashboardRecentTasksResponse,
    DashboardStatsResponse,
    DashboardSystemHealth,
    DashboardSystemHealthResponse,
)
from app.services.index_service import IndexService
from app.stores.conversation import ConversationStore
from app.stores.db import get_engine
from app.stores.eval_results import EvalResultStore
from app.stores.graph_schema_store import GraphSchemaStore
from app.stores.graph_store import GraphStore
from app.stores.index_metadata import IndexMetadataStore
from app.stores.user import UserStore

logger = structlog.get_logger()

# 健康检查单依赖超时（秒）
_HEALTH_CHECK_TIMEOUT = 2.0


class DashboardService:
    """聚合管理后台 Dashboard 各项指标，支持部分失败时返回安全默认值。"""

    def __init__(
        self,
        user_store: UserStore = None,
        conversation_store: ConversationStore = None,
        eval_store: EvalResultStore = None,
        index_metadata_store: IndexMetadataStore = None,
        index_service: IndexService = None,
        graph_schema_store: GraphSchemaStore = None,
        celery_app_instance=celery_app,
    ):
        self.user_store = user_store or UserStore()
        self.conversation_store = conversation_store or ConversationStore()
        self.eval_store = eval_store or EvalResultStore()
        self.index_metadata_store = index_metadata_store or IndexMetadataStore()
        self.index_service = index_service or IndexService()
        self.graph_schema_store = graph_schema_store or GraphSchemaStore()
        self.celery_app = celery_app_instance

    def get_dashboard(self, graph_store: GraphStore | None = None) -> AdminDashboardResponse:
        user_count = self._safe_count(
            "user_count", lambda: self.user_store.count()
        )
        conversation_count_today = self._safe_count(
            "conversation_count_today",
            lambda: self.conversation_store.count_today(),
        )
        index_status = self._safe_index_status()
        latest_eval_scores = self._safe_latest_eval_scores()
        recent_tasks = self._safe_recent_tasks()
        graph_rag_status = self._safe_graph_rag_status()
        system_health = self._safe_system_health(graph_store)

        return AdminDashboardResponse(
            user_count=user_count,
            conversation_count_today=conversation_count_today,
            index_status=index_status,
            latest_eval_scores=latest_eval_scores,
            recent_tasks=recent_tasks,
            graph_rag_status=graph_rag_status,
            system_health=system_health,
        )

    def get_stats(self) -> DashboardStatsResponse:
        user_count = self._safe_count(
            "user_count", lambda: self.user_store.count()
        )
        conversation_count_today = self._safe_count(
            "conversation_count_today",
            lambda: self.conversation_store.count_today(),
        )
        index_status = self._safe_index_status()
        latest_eval_scores = self._safe_latest_eval_scores()
        return DashboardStatsResponse(
            user_count=user_count,
            conversation_count_today=conversation_count_today,
            index_status=index_status,
            latest_eval_scores=latest_eval_scores,
        )

    def get_eval_scores(self) -> DashboardEvalScoresResponse:
        return DashboardEvalScoresResponse(
            latest_eval_scores=self._safe_latest_eval_scores()
        )

    def get_recent_tasks(self) -> DashboardRecentTasksResponse:
        return DashboardRecentTasksResponse(
            recent_tasks=self._safe_recent_tasks()
        )

    def get_graph_rag_status(self) -> DashboardGraphRagResponse:
        return DashboardGraphRagResponse(
            graph_rag_status=self._safe_graph_rag_status()
        )

    def get_system_health(
        self, graph_store: GraphStore | None = None
    ) -> DashboardSystemHealthResponse:
        return DashboardSystemHealthResponse(
            system_health=self._safe_system_health(graph_store)
        )

    def _safe_count(self, name: str, func) -> int:
        try:
            return int(func())
        except Exception as exc:
            logger.error(f"dashboard_{name}_failed", error=str(exc))
            return 0

    def _safe_index_status(self) -> DashboardIndexStatus:
        try:
            active_meta = self.index_metadata_store.get_active()
            last_tasks = self.index_service.get_recent_tasks(limit=1)
            last_task = last_tasks[0] if last_tasks else None
            return DashboardIndexStatus(
                is_ready=active_meta is not None,
                active_collection=active_meta.collection_name if active_meta else None,
                bm25_index_path=active_meta.bm25_index_path if active_meta else None,
                last_task_status=last_task.status if last_task else "unknown",
                last_task_updated_at=last_task.created_at if last_task else None,
            )
        except Exception as exc:
            logger.error("dashboard_index_status_failed", error=str(exc))
            return DashboardIndexStatus()

    def _safe_latest_eval_scores(self) -> DashboardEvalScores:
        try:
            scores = self.eval_store.get_latest_scores()
            return DashboardEvalScores(
                context_precision=_float_or_none(scores.get("context_precision")),
                context_recall=_float_or_none(scores.get("context_recall")),
                faithfulness=_float_or_none(scores.get("faithfulness")),
                answer_relevancy=_float_or_none(scores.get("answer_relevancy")),
            )
        except Exception as exc:
            logger.error("dashboard_latest_eval_scores_failed", error=str(exc))
            return DashboardEvalScores()

    def _safe_recent_tasks(self) -> list[DashboardRecentTask]:
        try:
            return self.index_service.get_recent_tasks(limit=5)
        except Exception as exc:
            logger.error("dashboard_recent_tasks_failed", error=str(exc))
            return []

    def _safe_graph_rag_status(self) -> DashboardGraphRagStatus:
        try:
            from datetime import datetime, timedelta

            from app.services.settings_service import SettingsService
            from app.stores.db import KbGraphSchema as KbGraphSchemaRow
            from app.stores.db import get_session_factory

            freshness_days = SettingsService().get_runtime_value("graphrag_freshness_threshold_days")
            session_factory = get_session_factory()
            with session_factory() as session:
                rows = session.query(KbGraphSchemaRow).all()

            total = len(rows)
            enabled = sum(1 for r in rows if r.enabled)

            # 找最近一次构建记录
            latest = None
            for r in rows:
                if r.last_build_at and (latest is None or r.last_build_at > latest.last_build_at):
                    latest = r

            # 新鲜度告警检查
            now = datetime.now(UTC)
            threshold = timedelta(days=freshness_days)
            for r in rows:
                if not r.enabled:
                    continue
                if r.last_build_at is None:
                    logger.warning(
                        "graphrag_freshness_alert",
                        kb_id=r.directory_id,
                        reason="never_built",
                        threshold_days=freshness_days,
                    )
                elif now - r.last_build_at.replace(tzinfo=UTC) > threshold:
                    logger.warning(
                        "graphrag_freshness_alert",
                        kb_id=r.directory_id,
                        reason="stale",
                        last_build_at=r.last_build_at.isoformat(),
                        threshold_days=freshness_days,
                    )

            return DashboardGraphRagStatus(
                enabled_kb_count=enabled,
                total_kb_count=total,
                last_build_at=latest.last_build_at.isoformat() if latest and latest.last_build_at else None,
                last_build_entities=latest.last_build_entities if latest else None,
                last_build_relations=latest.last_build_relations if latest else None,
                last_build_error=latest.last_build_error if latest else None,
                avg_query_duration_ms=None,  # TODO: 从结构化日志或指标系统聚合
            )
        except Exception as exc:
            logger.error("dashboard_graph_rag_status_failed", error=str(exc))
            return DashboardGraphRagStatus()

    def _safe_system_health(self, graph_store: GraphStore | None = None) -> DashboardSystemHealth:
        try:
            from functools import partial

            check_map: dict[str, Callable[[], DashboardDependencyStatus]] = {
                "MySQL": self._check_mysql,
                "Redis": self._check_redis,
                "Milvus": self._check_milvus,
                "Neo4j": partial(self._check_neo4j, graph_store),
                "Celery Workers": self._check_celery_workers,
                "Index Readiness": self._check_index_readiness,
            }

            dependencies: list[DashboardDependencyStatus] = []
            with ThreadPoolExecutor(max_workers=len(check_map)) as executor:
                future_to_name = {
                    executor.submit(fn): name for name, fn in check_map.items()
                }
                for future in as_completed(future_to_name, timeout=_HEALTH_CHECK_TIMEOUT):
                    name = future_to_name[future]
                    try:
                        dependencies.append(future.result())
                    except Exception as exc:
                        logger.error("dashboard_health_check_failed", dependency=name, error=str(exc))
                        dependencies.append(
                            DashboardDependencyStatus(
                                name=name,
                                status="unhealthy",
                                message=_truncate_message(str(exc), 200),
                            )
                        )

                # 处理在 as_completed 总窗口内仍未完成的依赖（理论上不会走到这里，因为 as_completed 已带超时）
                done = {f for f in future_to_name if f.done()}
                for future in future_to_name:
                    if future in done:
                        continue
                    name = future_to_name[future]
                    logger.warning(
                        "dashboard_health_check_timeout",
                        dependency=name,
                        timeout_seconds=_HEALTH_CHECK_TIMEOUT,
                    )
                    dependencies.append(
                        DashboardDependencyStatus(
                            name=name,
                            status="unhealthy",
                            message=f"健康检查超过 {_HEALTH_CHECK_TIMEOUT}s 未响应",
                        )
                    )

            status = self._aggregate_status(dependencies)
            return DashboardSystemHealth(
                status=status,
                dependencies=dependencies,
                checked_at=datetime.now(UTC).isoformat(),
            )
        except Exception as exc:
            logger.error("dashboard_system_health_failed", error=str(exc))
            return DashboardSystemHealth(status="unknown")

    def _check_dependency(self, name: str, check_fn: Callable[[], Any]) -> DashboardDependencyStatus:
        start = perf_counter()
        try:
            check_fn()
            latency_ms = round((perf_counter() - start) * 1000)
            return DashboardDependencyStatus(name=name, status="healthy", latency_ms=latency_ms)
        except Exception as exc:
            logger.error("dashboard_health_check_failed", dependency=name, error=str(exc))
            return DashboardDependencyStatus(
                name=name,
                status="unhealthy",
                message=_truncate_message(str(exc), 200),
            )

    def _check_mysql(self) -> DashboardDependencyStatus:
        def _ping():
            with get_engine().connect() as conn:
                conn.execute(text("SELECT 1"))

        return self._check_dependency("MySQL", _ping)

    def _check_redis(self) -> DashboardDependencyStatus:
        def _ping():
            settings = get_settings()
            client = redis.from_url(
                settings.redis_url,
                socket_connect_timeout=3,
                socket_timeout=3,
            )
            try:
                client.ping()
            finally:
                client.close()

        return self._check_dependency("Redis", _ping)

    def _check_milvus(self) -> DashboardDependencyStatus:
        def _ping():
            settings = get_settings()
            client = MilvusClient(uri=settings.milvus_uri)
            try:
                client.list_collections()
            finally:
                client.close()

        return self._check_dependency("Milvus", _ping)

    def _check_neo4j(self, graph_store: GraphStore | None = None) -> DashboardDependencyStatus:
        start = perf_counter()
        if graph_store is None or not graph_store.is_available:
            latency_ms = round((perf_counter() - start) * 1000)
            return DashboardDependencyStatus(
                name="Neo4j",
                status="degraded",
                latency_ms=latency_ms,
                message="Neo4j 未配置或连接不可用",
            )
        latency_ms = round((perf_counter() - start) * 1000)
        return DashboardDependencyStatus(name="Neo4j", status="healthy", latency_ms=latency_ms)

    def _check_celery_workers(self) -> DashboardDependencyStatus:
        def _ping():
            inspect = self.celery_app.control.inspect(timeout=1)
            # ping 比 active() 轻量，worker 存在即可认为健康
            pong = inspect.ping()
            if not pong:
                raise RuntimeError("没有可用的 Celery Worker")

        return self._check_dependency("Celery Workers", _ping)

    def _check_index_readiness(self) -> DashboardDependencyStatus:
        start = perf_counter()
        try:
            active = self.index_metadata_store.get_active("default")
            if active is None:
                return DashboardDependencyStatus(
                    name="Index Readiness",
                    status="degraded",
                    latency_ms=round((perf_counter() - start) * 1000),
                    message="无活跃索引",
                )
            return DashboardDependencyStatus(
                name="Index Readiness",
                status="healthy",
                latency_ms=round((perf_counter() - start) * 1000),
            )
        except Exception as exc:
            logger.error("dashboard_health_check_failed", dependency="Index Readiness", error=str(exc))
            return DashboardDependencyStatus(
                name="Index Readiness",
                status="unhealthy",
                message=_truncate_message(str(exc), 200),
            )

    @staticmethod
    def _aggregate_status(dependencies: list[DashboardDependencyStatus]) -> str:
        statuses = {d.status for d in dependencies}
        if "unhealthy" in statuses:
            return "unhealthy"
        if "degraded" in statuses:
            return "degraded"
        if statuses == {"healthy"}:
            return "healthy"
        return "unknown"


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _truncate_message(message: str, max_length: int = 200) -> str:
    if len(message) <= max_length:
        return message
    return message[:max_length] + "..."
