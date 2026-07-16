from celery import Celery

from app.services.settings_service import SettingsService

# broker/backend 在进程启动期读取（DB → .env → 默认），DB 覆盖在下次重启生效
_settings_service = SettingsService()
_redis_url = _settings_service.get_runtime_value("redis_url")

celery_app = Celery(
    "cloudbrief",
    broker=_redis_url,
    backend=_redis_url,
    include=["app.tasks.indexing", "app.tasks.graph_indexing"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    task_track_started=True,
    task_time_limit=3600,
    worker_prefetch_multiplier=1,
    task_routes={
        "app.tasks.indexing.index_file_task": {"queue": "kb.index.single"},
        "app.tasks.indexing.rebuild_index_task": {"queue": "kb.index.rebuild"},
        "app.tasks.graph_indexing.rebuild_graph_task": {"queue": "kb.graph.rebuild"},
        "app.tasks.graph_indexing.index_file_graph_task": {"queue": "kb.graph.rebuild"},
    },
)
