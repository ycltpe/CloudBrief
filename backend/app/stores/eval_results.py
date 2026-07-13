import json
from typing import Any

from app.models.schemas import HumanFeedbackIn
from app.stores.db import EvalResult, get_session_factory


class EvalResultStore:
    """RAGAS 评测过程数据与人工反馈持久化。"""

    def __init__(self, session_factory=None):
        self._session_factory = session_factory or get_session_factory()

    def create(
        self,
        question: str,
        contexts: list[dict[str, Any]],
        answer: str | None = None,
        ground_truth: str | None = None,
        ragas_scores: dict[str, Any] | None = None,
        reasoning: dict[str, Any] | None = None,
    ) -> EvalResult:
        with self._session_factory() as session:
            result = EvalResult(
                question=question,
                contexts_json=json.dumps(contexts, ensure_ascii=False),
                answer=answer,
                ground_truth=ground_truth,
                ragas_scores_json=json.dumps(ragas_scores or {}, ensure_ascii=False),
                reasoning_json=json.dumps(reasoning or {}, ensure_ascii=False),
            )
            session.add(result)
            session.commit()
            session.refresh(result)
            return result

    def list_all(self, limit: int = 100, offset: int = 0) -> list[EvalResult]:
        with self._session_factory() as session:
            return (
                session.query(EvalResult)
                .order_by(EvalResult.created_at.desc())
                .offset(offset)
                .limit(limit)
                .all()
            )

    def list_with_filters(
        self,
        limit: int = 20,
        offset: int = 0,
        min_score: float | None = None,
        has_feedback: bool | None = None,
    ) -> tuple[list[EvalResult], int]:
        """返回筛选后的评测记录及总数。

        min_score 针对 ragas_scores 中的 faithfulness 字段进行过滤。
        has_feedback 为 True 表示已有人工评分或反馈标记，False 表示完全没有人工反馈。
        """
        with self._session_factory() as session:
            all_results = (
                session.query(EvalResult)
                .order_by(EvalResult.created_at.desc())
                .all()
            )

        filtered = []
        for result in all_results:
            if min_score is not None:
                try:
                    scores = json.loads(result.ragas_scores_json or "{}")
                    faithfulness = scores.get("faithfulness")
                except (json.JSONDecodeError, TypeError):
                    faithfulness = None
                if faithfulness is None or float(faithfulness) < min_score:
                    continue

            if has_feedback is not None:
                has_any_feedback = bool(
                    result.human_score is not None
                    or result.is_adopted
                    or result.is_modified
                    or (result.human_note and result.human_note.strip())
                )
                if has_feedback != has_any_feedback:
                    continue

            filtered.append(result)

        total = len(filtered)
        return filtered[offset : offset + limit], total

    def get(self, result_id: int) -> EvalResult | None:
        with self._session_factory() as session:
            return session.query(EvalResult).filter_by(id=result_id).first()

    def update_feedback(self, result_id: int, feedback: HumanFeedbackIn) -> EvalResult | None:
        with self._session_factory() as session:
            result = session.query(EvalResult).filter_by(id=result_id).first()
            if not result:
                return None
            if feedback.human_score is not None:
                result.human_score = feedback.human_score
            if feedback.human_note is not None:
                result.human_note = feedback.human_note
            result.is_adopted = feedback.is_adopted
            result.is_modified = feedback.is_modified
            session.commit()
            session.refresh(result)
            return result

    def get_latest_scores(self) -> dict[str, Any]:
        """返回最新一次评测的 RAGAS 分数字典。"""
        with self._session_factory() as session:
            result = (
                session.query(EvalResult)
                .order_by(EvalResult.created_at.desc())
                .first()
            )
        if not result:
            return {}
        try:
            return json.loads(result.ragas_scores_json or "{}")
        except (json.JSONDecodeError, TypeError):
            return {}
