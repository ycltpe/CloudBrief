"""Agentic 编排 StateGraph 与中断恢复测试。"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from app.models.schemas import Citation
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
def settings_service():
    svc = MagicMock()
    svc.get_runtime_value = MagicMock(side_effect=lambda key: {
        "agentic_interrupt_enabled": False,
        "refusal_threshold": 0.3,
        "stale_threshold_days": 90,
    }.get(key))
    return svc


class TestAgenticGraphLinearFlow:
    """验证 direct 路径：改写 → 规划 → 检索 → 评分 → 生成。"""

    async def test_stream_yields_expected_events(self, mock_deps, settings_service):
        runner = AgentGraphRunner(mock_deps, settings_service=settings_service)
        events = []
        async for event in runner.stream(
            {
                "question": "测试问题",
                "conversation_id": "conv-1",
                "kb_id": "default",
                "history": [],
            },
            thread_id="conv-1",
        ):
            events.append(event)

        types = [e.type for e in events]
        assert "sources" in types
        assert "chunk" in types
        assert "citations" in types
        assert "done" in types
        assert not runner.interrupted
        assert runner.final_state.get("answer") == "这是答案"
        assert runner.final_state.get("max_score") == 0.95


class TestAgenticGraphRouting:
    """验证条件边路由。"""

    async def test_low_score_triggers_rewrite_and_then_refusal(self, mock_deps, settings_service):
        # 所有检索结果都低分
        grade = GradeOutput(is_relevant=False, score=0.1, reason="不相关")
        mock_deps.grade_stage.execute = MagicMock(return_value=grade)

        runner = AgentGraphRunner(mock_deps, settings_service=settings_service)
        events = [e async for e in runner.stream(
            {"question": "低分问题", "conversation_id": "conv-low", "kb_id": "default", "history": []},
            thread_id="conv-low",
        )]

        # 第一次 retrieve 后 grade 不通过 -> rewrite -> 第二次 retrieve -> grade 仍不通过 -> refusal
        types = [e.type for e in events]
        assert "chunk" in types  # refusal 输出 chunk
        assert "citations" in types
        assert "done" in types
        assert runner.final_state.get("is_refusal") is True

    async def test_empty_results_goes_to_refusal(self, mock_deps, settings_service):
        mock_deps.retrieval_pipeline.retrieve = MagicMock(return_value=MagicMock(results=[], is_fallback=False))
        runner = AgentGraphRunner(mock_deps, settings_service=settings_service)
        [e async for e in runner.stream(
            {"question": "空检索", "conversation_id": "conv-empty", "kb_id": "default", "history": []},
            thread_id="conv-empty",
        )]
        assert runner.final_state.get("is_refusal") is True


class TestAgenticGraphInterrupt:
    """验证多跳中断与恢复。"""

    async def test_multi_hop_interrupt_and_resume(self, mock_deps, settings_service):
        settings_service.get_runtime_value = MagicMock(side_effect=lambda key: {
            "agentic_interrupt_enabled": True,
            "refusal_threshold": 0.3,
            "stale_threshold_days": 90,
        }.get(key))

        # 让 plan 返回多跳步骤，触发 multi_hop_decompose
        mock_deps.plan_stage.execute = MagicMock(return_value=PlanOutput(steps=["步骤1", "步骤2"]))

        runner = AgentGraphRunner(
            mock_deps,
            settings_service=settings_service,
            checkpointer=InMemorySaver(),
        )

        # 首次执行应在中断点暂停
        first_events = []
        async for event in runner.stream(
            {"question": "多跳问题", "conversation_id": "conv-mh", "kb_id": "default", "history": []},
            thread_id="conv-mh",
        ):
            first_events.append(event)

        assert runner.interrupted is True
        assert runner.interrupt_value is not None
        assert runner.interrupt_value.get("sub_questions") == ["子问题1", "子问题2"]
        status_event = next((e for e in first_events if e.type == "status"), None)
        assert status_event is not None
        assert status_event.data.get("step") == "interrupted"

        # 恢复执行
        resumed_events = []
        async for event in runner.resume(thread_id="conv-mh", resume_payload={"confirmed": True}):
            resumed_events.append(event)

        assert not runner.interrupted
        assert runner.final_state.get("answer") == "这是答案"
        assert any(e.type == "done" for e in resumed_events)

    async def test_multi_hop_without_interrupt_when_disabled(self, mock_deps, settings_service):
        # 默认关闭中断，应直接走完
        mock_deps.plan_stage.execute = MagicMock(return_value=PlanOutput(steps=["步骤1", "步骤2"]))
        runner = AgentGraphRunner(mock_deps, settings_service=settings_service)
        [e async for e in runner.stream(
            {"question": "多跳问题", "conversation_id": "conv-mh-off", "kb_id": "default", "history": []},
            thread_id="conv-mh-off",
        )]
        assert not runner.interrupted
        assert runner.final_state.get("answer") == "这是答案"


class TestAgenticGraphStateContract:
    """验证图状态复用现有 RetrievalResult 契约。"""

    async def test_state_uses_retrieval_result(self, mock_deps, settings_service):
        runner = AgentGraphRunner(mock_deps, settings_service=settings_service)
        [e async for e in runner.stream(
            {"question": "状态契约", "conversation_id": "conv-state", "kb_id": "default", "history": []},
            thread_id="conv-state",
        )]
        results = runner.final_state.get("retrieval_results", [])
        assert len(results) == 1
        assert isinstance(results[0], RetrievalResult)
        assert results[0].score == 0.95

    async def test_tool_trace_is_appended(self, mock_deps, settings_service):
        runner = AgentGraphRunner(mock_deps, settings_service=settings_service)
        [e async for e in runner.stream(
            {"question": "轨迹", "conversation_id": "conv-trace", "kb_id": "default", "history": []},
            thread_id="conv-trace",
        )]
        tool_trace = runner.final_state.get("tool_trace", [])
        nodes = {entry["node"] for entry in tool_trace}
        assert "rewrite" in nodes
        assert "plan" in nodes
        assert "retrieve" in nodes
        assert "grade" in nodes
        assert "generate" in nodes
