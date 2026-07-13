import json
from difflib import SequenceMatcher

from app.stores.db import GraphShadowRecord, get_session_factory


class GraphShadowStore:
    """GraphRAG shadow mode 对比数据持久化仓库。"""

    def __init__(self, session_factory=None):
        self._session_factory = session_factory or get_session_factory()

    @staticmethod
    def _compute_diff_ratio(vector_answer: str, graph_answer: str) -> float:
        if not vector_answer or not graph_answer:
            return 0.0
        return SequenceMatcher(None, vector_answer, graph_answer).ratio()

    def record(
        self,
        *,
        kb_id: str,
        user_id: int | None,
        question: str,
        vector_answer: str,
        graph_answer: str | None,
        subgraph_context_json: str = "{}",
    ) -> GraphShadowRecord:
        diff_ratio = self._compute_diff_ratio(vector_answer, graph_answer or "")
        with self._session_factory() as session:
            record = GraphShadowRecord(
                kb_id=kb_id,
                user_id=user_id,
                question=question,
                vector_answer=vector_answer,
                graph_answer=graph_answer,
                subgraph_context_json=subgraph_context_json,
                diff_metrics_json=json.dumps(
                    {"diff_ratio": diff_ratio, "vector_len": len(vector_answer), "graph_len": len(graph_answer or "")},
                    ensure_ascii=False,
                ),
            )
            session.add(record)
            session.commit()
            session.refresh(record)
            return record

    def list_records(
        self,
        kb_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[GraphShadowRecord], int]:
        with self._session_factory() as session:
            query = session.query(GraphShadowRecord)
            if kb_id:
                query = query.filter_by(kb_id=kb_id)
            total = query.count()
            records = (
                query.order_by(GraphShadowRecord.created_at.desc())
                .offset(offset)
                .limit(limit)
                .all()
            )
            return records, total

    def summary(self, kb_id: str | None = None) -> dict:
        records, total = self.list_records(kb_id=kb_id, limit=10000)
        if not records:
            return {"count": 0, "avg_diff_ratio": None, "last_record_at": None}
        ratios = []
        last_at = None
        for r in records:
            try:
                metrics = json.loads(r.diff_metrics_json or "{}")
                ratios.append(metrics.get("diff_ratio", 0.0))
            except Exception:
                continue
            if r.created_at and (last_at is None or r.created_at > last_at):
                last_at = r.created_at
        return {
            "count": total,
            "avg_diff_ratio": sum(ratios) / len(ratios) if ratios else None,
            "last_record_at": last_at.isoformat() if last_at else None,
        }
