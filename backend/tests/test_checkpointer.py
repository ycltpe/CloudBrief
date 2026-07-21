"""LangGraph checkpointer 工厂与后端切换测试。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.schemas import Citation
from app.orchestration.checkpointer import (
    close_checkpointer,
    get_checkpointer,
    get_redis_checkpointer_async,
    get_sqlite_checkpointer_async,
)
from app.orchestration.runner import AgentGraphRunner, AgenticGraphDeps
from app.pipelines.generation import GenerationPipeline, StreamEvent
from app.stages.base import RetrievalResult
from app.stages.grade import GradeOutput, GradeStage
from app.stages.multi_hop_decompose import MultiHopDecomposeOutput, MultiHopDecomposeStage
from app.stages.plan import PlanOutput, PlanStage
from app.stages.query_rewrite import QueryRewriteOutput, QueryRewriteStage


@pytest.fixture
def retrieval_result():
    return RetrievalResult(
        chunk_id="chunk-1",
        content="测试内容",
        source_type="faq",
        title="测试标题",
        updated_at=datetime.utcnow(),
        source_id="faq/test.md",
        score=0.95,
    )


@pytest.fixture
def mock_deps(retrieval_result):
    retrieval_output = MagicMock()
    retrieval_output.results = [retrieval_result]
    retrieval_output.is_fallback = False

    retrieval_pipeline = MagicMock()
    retrieval_pipeline.retrieve = MagicMock(return_value=retrieval_output)

    async def _mock_generate_stream(input_data):
        yield StreamEvent(type="chunk", data={"content": "这是答案"})
        yield StreamEvent(
            type="citations",
            data={
                "citations": [Citation(
                    chunk_id="chunk-1",
                    source_title="测试标题",
                    source_type="faq",
                    updated_at=datetime.utcnow().isoformat(),
                    content_summary="测试内容摘要",
                ).model_dump()],
                "is_refusal": False,
                "is_stale": False,
            },
        )
        yield StreamEvent(type="done", data={})

    generation_pipeline = MagicMock(spec=GenerationPipeline)
    generation_pipeline.generate_stream = _mock_generate_stream

    query_rewrite_stage = MagicMock(spec=QueryRewriteStage)
    query_rewrite_stage.execute = MagicMock(return_value=QueryRewriteOutput(rewritten_query="改写后的问题"))

    grade_stage = MagicMock(spec=GradeStage)
    grade_stage.execute = MagicMock(return_value=GradeOutput(is_relevant=True, score=0.95, reason="相关"))

    plan_stage = MagicMock(spec=PlanStage)
    plan_stage.execute = MagicMock(return_value=PlanOutput(steps=["改写后的问题"]))

    multi_hop_decompose_stage = MagicMock(spec=MultiHopDecomposeStage)
    multi_hop_decompose_stage.execute = MagicMock(
        return_value=MultiHopDecomposeOutput(sub_questions=["子问题1", "子问题2"])
    )

    return AgenticGraphDeps(
        retrieval_pipeline=retrieval_pipeline,
        generation_pipeline=generation_pipeline,
        query_rewrite_stage=query_rewrite_stage,
        grade_stage=grade_stage,
        plan_stage=plan_stage,
        multi_hop_decompose_stage=multi_hop_decompose_stage,
    )


@pytest.fixture
def settings_service(tmp_path):
    svc = MagicMock()
    svc.get_runtime_value = MagicMock(side_effect=lambda key: {
        "checkpoint_backend": "sqlite",
        "checkpoint_sqlite_path": str(tmp_path / "checkpoints.sqlite"),
        "redis_url": "redis://localhost:6381/0",
        "checkpoint_redis_prefix": "test:checkpoint",
        "checkpoint_redis_ttl": 0,
    }.get(key))
    return svc


class TestCheckpointerFactory:
    """验证工厂按 ``checkpoint_backend`` 返回对应 saver。"""

    async def test_default_backend_returns_sqlite(self, settings_service, tmp_path):
        saver = await get_checkpointer(settings_service=settings_service)
        assert saver.__class__.__name__ == "AsyncSqliteSaver"
        assert Path(settings_service.get_runtime_value("checkpoint_sqlite_path")).parent.exists()
        await close_checkpointer(saver)

    async def test_explicit_sqlite_backend(self, settings_service):
        saver = await get_checkpointer("sqlite", settings_service=settings_service)
        assert saver.__class__.__name__ == "AsyncSqliteSaver"
        await close_checkpointer(saver)

    async def test_redis_backend_returns_redis_saver(self, settings_service):
        with patch(
            "langgraph.checkpoint.redis.aio.AsyncRedisSaver",
            autospec=True,
        ) as mock_cls:
            mock_instance = MagicMock()
            mock_instance._owns_its_client = True
            mock_instance._redis = MagicMock()
            mock_cls.return_value = mock_instance

            saver = await get_checkpointer("redis", settings_service=settings_service)

            assert saver is mock_instance
            mock_cls.assert_called_once()
            call_kwargs = mock_cls.call_args.kwargs
            assert call_kwargs["redis_url"] == "redis://localhost:6381/0"
            assert call_kwargs["checkpoint_prefix"] == "test:checkpoint"
            assert call_kwargs["checkpoint_write_prefix"] == "test:checkpoint_write"
            assert call_kwargs["ttl"] is None

    async def test_redis_backend_uses_ttl_when_configured(self, settings_service):
        settings_service.get_runtime_value = MagicMock(side_effect=lambda key: {
            "checkpoint_backend": "redis",
            "checkpoint_sqlite_path": "/tmp/checkpoints.sqlite",
            "redis_url": "redis://localhost:6381/0",
            "checkpoint_redis_prefix": "test:checkpoint",
            "checkpoint_redis_ttl": 10080,
        }.get(key))

        with patch(
            "langgraph.checkpoint.redis.aio.AsyncRedisSaver",
            autospec=True,
        ) as mock_cls:
            mock_instance = MagicMock()
            mock_instance._owns_its_client = True
            mock_instance._redis = MagicMock()
            mock_cls.return_value = mock_instance

            await get_checkpointer("redis", settings_service=settings_service)

            call_kwargs = mock_cls.call_args.kwargs
            assert call_kwargs["ttl"] == {
                "default_ttl": 10080,
                "refresh_on_read": False,
            }


class TestCheckpointerClose:
    """验证 close_checkpointer 能安全关闭 SQLite 与 Redis 连接。"""

    async def test_close_sqlite_saver(self, settings_service):
        saver = await get_sqlite_checkpointer_async(
            settings_service.get_runtime_value("checkpoint_sqlite_path")
        )
        await close_checkpointer(saver)
        # 关闭后再执行应抛异常
        with pytest.raises(Exception):  # noqa: B017
            await saver.conn.execute("SELECT 1")

    async def test_close_redis_saver_owned_client(self):
        saver = MagicMock()
        saver._owns_its_client = True
        saver._redis = AsyncMock()
        saver.conn = None
        await close_checkpointer(saver)
        saver._redis.aclose.assert_awaited_once()

    async def test_close_redis_saver_external_client(self):
        saver = MagicMock()
        saver._owns_its_client = False
        saver._redis = AsyncMock()
        saver.conn = None
        await close_checkpointer(saver)
        saver._redis.aclose.assert_not_called()


class TestSQLitePersistence:
    """验证 SQLite checkpointer 可跨 runner 恢复状态。"""

    async def test_state_persists_across_runners(self, mock_deps, settings_service, tmp_path):
        # 复用 settings_service fixture 但指定到同一 SQLite 文件
        settings_service.get_runtime_value = MagicMock(side_effect=lambda key: {
            "checkpoint_backend": "sqlite",
            "checkpoint_sqlite_path": str(tmp_path / "persist.sqlite"),
            "redis_url": "redis://localhost:6381/0",
            "checkpoint_redis_prefix": "test:checkpoint",
            "checkpoint_redis_ttl": 0,
            "agentic_interrupt_enabled": True,
            "refusal_threshold": 0.3,
            "stale_threshold_days": 90,
        }.get(key))

        # 第一个 runner：触发多跳中断后关闭
        mock_deps.plan_stage.execute = MagicMock(
            return_value=PlanOutput(steps=["步骤1", "步骤2"])
        )
        runner1 = await AgentGraphRunner.create(mock_deps, settings_service=settings_service)
        first_events = []
        async for event in runner1.stream(
            {"question": "多跳问题", "conversation_id": "conv-persist", "kb_id": "default", "history": []},
            thread_id="conv-persist",
        ):
            first_events.append(event)
        assert runner1.interrupted is True
        await runner1.close()

        # 第二个 runner：从同一 SQLite 文件恢复并继续执行
        runner2 = await AgentGraphRunner.create(mock_deps, settings_service=settings_service)
        resumed_events = []
        async for event in runner2.resume(thread_id="conv-persist", resume_payload={"confirmed": True}):
            resumed_events.append(event)
        assert runner2.interrupted is False
        assert runner2.final_state.get("answer") == "这是答案"
        assert any(e.type == "done" for e in resumed_events)
        await runner2.close()

    async def test_get_redis_checkpointer_factory(self):
        with patch(
            "langgraph.checkpoint.redis.aio.AsyncRedisSaver",
            autospec=True,
        ) as mock_cls:
            mock_instance = MagicMock()
            mock_cls.return_value = mock_instance
            saver = await get_redis_checkpointer_async(
                "redis://localhost:6381/0",
                checkpoint_prefix="test:cp",
                ttl_minutes=60,
            )
            assert saver is mock_instance
            call_kwargs = mock_cls.call_args.kwargs
            assert call_kwargs["redis_url"] == "redis://localhost:6381/0"
            assert call_kwargs["checkpoint_prefix"] == "test:cp"
            assert call_kwargs["ttl"] == {"default_ttl": 60, "refresh_on_read": False}
