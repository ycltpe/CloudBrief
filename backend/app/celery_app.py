from celery import Celery

from app.config import get_settings

settings = get_settings()

celery_app = Celery(
    "cloudbrief",
    broker=settings.redis_url,
    backend=settings.redis_url,
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
