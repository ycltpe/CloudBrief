from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.index_service import IndexService


class _FakePubSub:
    def __init__(self, messages):
        self.messages = messages
        self.subscribe_calls = []

    async def subscribe(self, channel):
        self.subscribe_calls.append(channel)

    async def unsubscribe(self, channel):
        pass

    async def close(self):
        pass

    async def listen(self):
        for message in self.messages:
            yield message


def _make_step(name="parse", status="completed", log=None, updated_at=None):
    row = MagicMock()
    row.step_name = name
    row.status = status
    row.duration_ms = 123
    row.log = log
    row.updated_at = updated_at or datetime.utcnow()
    return row


def test_trigger_file_index_records_recent_task():
    svc = IndexService()
    with patch.object(svc, "_record_recent_task") as mock_record:
        with patch("app.tasks.indexing.index_file_task") as mock_task:
            mock_task.delay.return_value = MagicMock(id="task-file-1")
            task_id = svc.trigger_file_index(42)

    assert task_id == "task-file-1"
    mock_task.delay.assert_called_once_with(file_id=42)
    mock_record.assert_called_once_with("task-file-1", task_type="file")


def test_trigger_rebuild_records_recent_task():
    svc = IndexService()
    with patch.object(svc, "_record_recent_task") as mock_record:
        with patch("app.tasks.indexing.rebuild_index_task") as mock_task:
            mock_task.delay.return_value = MagicMock(id="task-rebuild-1")
            task_id = svc.trigger_rebuild()

    assert task_id == "task-rebuild-1"
    mock_record.assert_called_once_with("task-rebuild-1", task_type="rebuild", kb_id="default")


def test_get_task_status_aggregates_steps_and_error():
    step_rows = [
        _make_step("parse", "completed"),
        _make_step("task", "failed", log="boom"),
    ]
    task_store = MagicMock()
    task_store.list_steps.return_value = step_rows
    svc = IndexService(task_step_store=task_store)

    with patch("app.services.index_service.AsyncResult") as mock_result_cls:
        mock_result = MagicMock()
        mock_result.status = "FAILURE"
        mock_result.result = "boom"
        mock_result_cls.return_value = mock_result

        status = svc.get_task_status("task-1")

    assert status.task_id == "task-1"
    assert status.status == "failed"
    assert status.error == "boom"
    assert len(status.steps) == 2
    task_store.list_steps.assert_called_once_with("task-1", after_updated_at=None)


def test_get_recent_tasks_maps_celery_status():
    svc = IndexService()
    payload = (
        '{"task_id":"recent-1","task_type":"rebuild","kb_id":"default","created_at":"2026-07-13T00:00:00"}'
    )

    redis_client = MagicMock()
    redis_client.zrevrange.return_value = [payload]
    with patch("app.services.index_service.redis.from_url", return_value=redis_client):
        with patch("app.services.index_service.AsyncResult") as mock_result_cls:
            mock_result = MagicMock()
            mock_result.status = "SUCCESS"
            mock_result_cls.return_value = mock_result
            tasks = svc.get_recent_tasks(limit=5)

    assert len(tasks) == 1
    assert tasks[0].task_id == "recent-1"
    assert tasks[0].status == "completed"


async def test_event_stream_replays_persisted_steps():
    import json

    updated = datetime.utcnow()
    step_rows = [
        _make_step("parse", "completed", log="parsed 1 doc", updated_at=updated),
    ]
    task_store = MagicMock()
    task_store.list_steps.return_value = step_rows
    svc = IndexService(task_step_store=task_store)

    pubsub = _FakePubSub([])
    redis_client = AsyncMock()
    redis_client.pubsub = MagicMock(return_value=pubsub)
    fake_aioredis = MagicMock()
    fake_aioredis.from_url.return_value = redis_client

    with patch("app.services.index_service.aioredis", fake_aioredis):
        events = []
        async for event in svc.event_stream("task-1"):
            events.append(event)

    assert len(events) == 1
    data = events[0]
    assert data["event"] == "step"
    payload = json.loads(data["data"])
    assert payload["step"] == "parse"
    assert payload["status"] == "completed"


async def test_event_stream_subscribes_and_yields_live_messages():
    import json

    task_store = MagicMock()
    task_store.list_steps.return_value = []
    svc = IndexService(task_step_store=task_store)

    message = {
        "type": "message",
        "data": '{"task_id":"task-1","step":"chunking","status":"running","timestamp":"2026-07-13T00:00:00"}',
    }
    pubsub = _FakePubSub([message])
    redis_client = AsyncMock()
    redis_client.pubsub = MagicMock(return_value=pubsub)
    fake_aioredis = MagicMock()
    fake_aioredis.from_url.return_value = redis_client

    with patch("app.services.index_service.aioredis", fake_aioredis):
        events = []
        async for event in svc.event_stream("task-1"):
            events.append(event)
            # 手动终止，否则空 listen 会阻塞测试
            break

    assert len(events) == 1
    payload = json.loads(events[0]["data"])
    assert payload["step"] == "chunking"
    assert "index:task:task-1" in pubsub.subscribe_calls
