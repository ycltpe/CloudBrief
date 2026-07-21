"""LangGraph 编排状态定义。

复用现有 ``RetrievalResult`` Pydantic 契约，避免引入额外的 DTO 转换层。
"""

from __future__ import annotations

from typing import Annotated, Literal, TypedDict

from app.stages.base import RetrievalResult


class AgentState(TypedDict):
    """Agentic 问答流程的图状态。

    字段按执行阶段逐步写入；``retrieval_results`` 使用 append reducer，
    多跳子问题检索结果可累计汇总。
    """

    # ---- 输入 ----
    question: str
    history: list[dict]
    kb_id: str
    conversation_id: str

    # ---- 改写 ----
    rewritten_query: str

    # ---- 规划 ----
    plan_route: Literal["direct", "multi_hop", "graph"] | None
    plan_reason: str

    # ---- 多跳 ----
    sub_questions: list[str]

    # ---- 检索 ----
    # 每次 retrieve/multi_hop_retrieve 节点返回完整列表，直接覆盖当前值
    retrieval_results: list[RetrievalResult]
    is_fallback: bool
    max_score: float
    retrieval_metadata: dict | None

    # ---- 评分 ----
    grade_passed: bool
    grade_reason: str
    hop_count: int

    # ---- 生成 ----
    answer: str
    citations: list[dict]
    is_refusal: bool
    is_stale: bool

    # ---- 可观测 ----
    tool_trace: Annotated[list[dict], append_reducer]

    # ---- 中断/恢复 ----
    interrupt_value: dict | None
    resume_payload: dict | None


def append_reducer(left: list | None, right: list | None) -> list:
    """LangGraph reducer：将右侧增量追加到左侧列表。"""
    if left is None:
        left = []
    if right is None:
        return left
    return left + right
