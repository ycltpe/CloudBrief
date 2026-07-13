import json
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

import redis
import redis.asyncio as aioredis
import structlog
from celery.result import AsyncResult
from fastapi import Request

from app.celery_app import celery_app
from app.config import get_settings
from app.models.schemas import DashboardRecentTask, IndexStep, IndexTaskStatus

logger = structlog.get_logger()


class IndexService:
    """编排索引任务：触发 Celery、查询状态、SSE 事件流。"""

    def __init__(self, task_step_store=None):
        self.settings = get_settings()
        from app.stores.index_task_step import IndexTaskStepStore

        self.task_step_store = task_step_store or IndexTaskStepStore()

    def trigger_rebuild(self, kb_id: str = "default") -> str:
        from app.tasks.indexing import rebuild_index_task

        task = rebuild_index_task.delay(kb_id=kb_id)
        task_id = task.id
        self._record_recent_task(task_id, task_type="rebuild", kb_id=kb_id)
        return task_id

    def trigger_file_index(self, file_id: int) -> str:
        from app.tasks.indexing import index_file_task

        task = index_file_task.delay(file_id=file_id)
        task_id = task.id
        self._record_recent_task(task_id, task_type="file")
        return task_id

    def trigger_graph_rebuild(self, kb_id: str) -> str:
        from app.tasks.graph_indexing import rebuild_graph_task

        task = rebuild_graph_task.delay(kb_id=kb_id)
        task_id = task.id
        self._record_recent_task(task_id, task_type="graph", kb_id=kb_id)
        return task_id

    def _record_recent_task(self, task_id: str, task_type: str = "rebuild", kb_id: str = "default") -> None:
        """把新触发任务记录到 Redis 有序集合，供 Dashboard 展示最近任务。"""
        redis_client = redis.from_url(self.settings.redis_url)
        try:
            now = datetime.utcnow()
            payload = json.dumps(
                {"task_id": task_id, "task_type": task_type, "kb_id": kb_id, "created_at": now.isoformat()},
                ensure_ascii=False,
            )
            redis_client.zadd(f"index:recent_tasks:{kb_id}", {payload: now.timestamp()})
            redis_client.zadd("index:recent_tasks", {payload: now.timestamp()})
            redis_client.zremrangebyrank("index:recent_tasks", 0, -51)
            redis_client.zremrangebyrank(f"index:recent_tasks:{kb_id}", 0, -51)
        except Exception as exc:
            logger.warning("index_record_recent_task_failed", task_id=task_id, error=str(exc))
        finally:
            redis_client.close()

    def get_recent_tasks(self, limit: int = 5) -> list[DashboardRecentTask]:
        """读取最近触发的索引重建任务列表，并补充当前 Celery 状态。"""
        redis_client = redis.from_url(self.settings.redis_url)
        try:
            raw_items = redis_client.zrevrange("index:recent_tasks", 0, limit - 1)
        except Exception as exc:
            logger.warning("index_read_recent_tasks_failed", error=str(exc))
            return []
        finally:
            redis_client.close()

        tasks: list[DashboardRecentTask] = []
        for raw in raw_items:
            try:
                item = json.loads(raw)
                task_id = item.get("task_id")
                created_at = item.get("created_at")
                status = self._normalize_status(
                    AsyncResult(task_id, app=celery_app).status
                )
                tasks.append(
                    DashboardRecentTask(
                        task_id=task_id,
                        status=status,  # type: ignore[arg-type]
                        created_at=created_at,
                    )
                )
            except Exception as exc:
                logger.warning("index_parse_recent_task_failed", raw=raw, error=str(exc))
                continue
        return tasks

    def get_task_status(self, task_id: str) -> IndexTaskStatus:
        result = AsyncResult(task_id, app=celery_app)
        status = self._normalize_status(result.status)

        steps = self._load_steps(task_id)

        created_at = None
        updated_at = None
        error = None
        if steps:
            created_at = steps[0].created_at
            updated_at = steps[-1].created_at
        for step in steps:
            if step.name == "task" and step.status == "failed" and step.log:
                error = step.log
                break

        if error is None and status == "failed" and isinstance(result.result, str):
            error = result.result

        return IndexTaskStatus(
            task_id=task_id,
            status=status,  # type: ignore[arg-type]
            steps=steps,
            created_at=created_at,
            updated_at=updated_at or datetime.utcnow().isoformat(),
            error=error,
        )

    async def event_stream(
        self,
        task_id: str,
        request: Request | None = None,
        last_event_id: str | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        redis_client = aioredis.from_url(self.settings.redis_url)
        channel = f"index:task:{task_id}"
        pubsub = redis_client.pubsub()
        await pubsub.subscribe(channel)

        after = None
        if last_event_id:
            try:
                after = datetime.fromisoformat(last_event_id)
            except ValueError:
                after = None

        last_replayed = after
        # 先重放数据库中已保存的步骤
        for step in self.task_step_store.list_steps(task_id, after_updated_at=after):
            payload = {
                "task_id": task_id,
                "step": step.step_name,
                "status": step.status,
                "duration_ms": step.duration_ms,
                "log": step.log,
                "timestamp": step.updated_at.isoformat(),
            }
            yield {"event": "step", "data": json.dumps(payload, ensure_ascii=False)}
            if last_replayed is None or step.updated_at > last_replayed:
                last_replayed = step.updated_at

        try:
            async for message in pubsub.listen():
                if request is not None and await request.is_disconnected():
                    break
                if message["type"] != "message":
                    continue
                try:
                    event = json.loads(message["data"])
                    # 避免重放与实时消息之间的重复
                    if last_replayed is not None and event.get("timestamp"):
                        msg_ts = datetime.fromisoformat(event["timestamp"])
                        if msg_ts <= last_replayed:
                            continue
                    yield {"event": "step", "data": json.dumps(event, ensure_ascii=False)}
                    if event.get("step") == "task" and event.get("status") in (
                        "completed",
                        "failed",
                    ):
                        break
                except (json.JSONDecodeError, ValueError):
                    logger.warning("invalid_sse_message", data=message["data"])
        finally:
            await pubsub.unsubscribe(channel)
            await pubsub.close()
            await redis_client.close()

    def _load_steps(
        self,
        task_id: str,
        after_timestamp: str | None = None,
    ) -> list[IndexStep]:
        after = None
        if after_timestamp:
            try:
                after = datetime.fromisoformat(after_timestamp)
            except ValueError:
                after = None

        rows = self.task_step_store.list_steps(task_id, after_updated_at=after)
        return [
            IndexStep(
                name=row.step_name,
                status=row.status,  # type: ignore[arg-type]
                duration_ms=row.duration_ms,
                log=row.log,
                created_at=row.updated_at.isoformat(),
            )
            for row in rows
        ]

    @staticmethod
    def _normalize_status(celery_status: str) -> str:
        mapping = {
            "PENDING": "pending",
            "STARTED": "running",
            "SUCCESS": "completed",
            "FAILURE": "failed",
            "RETRY": "running",
        }
        return mapping.get(celery_status, celery_status.lower())
