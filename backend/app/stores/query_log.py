import hashlib
import json
import re
from datetime import datetime
from typing import Any

from app.stores.db import QueryLog, get_session_factory


class QueryLogStore:
    """真实用户查询日志持久化仓库。"""

    def __init__(self, session_factory=None):
        self._session_factory = session_factory or get_session_factory()

    @staticmethod
    def _hash(value: str, salt: str = "cloudbrief") -> str:
        return hashlib.sha256(f"{value}:{salt}".encode()).hexdigest()

    @staticmethod
    def _desensitize(text: str) -> str:
        """脱敏：手机号、邮箱、身份证号、工号。"""
        if not text:
            return text
        # 手机号
        text = re.sub(r"1[3-9]\d{9}", "[PHONE]", text)
        # 邮箱
        text = re.sub(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", "[EMAIL]", text)
        # 身份证号（18位或15位）
        text = re.sub(r"\b\d{17}[\dXx]|\d{15}\b", "[ID]", text)
        # 工号（假设为 5-10 位数字或字母数字组合）
        text = re.sub(r"\b[A-Z]{2,4}\d{5,10}\b", "[EMPLOYEE_ID]", text)
        return text

    @staticmethod
    def _desensitize_value(value: Any) -> Any:
        """递归脱敏字符串，嵌套字典/列表保持结构。"""
        if isinstance(value, str):
            return QueryLogStore._desensitize(value)
        if isinstance(value, list):
            return [QueryLogStore._desensitize_value(v) for v in value]
        if isinstance(value, dict):
            return {k: QueryLogStore._desensitize_value(v) for k, v in value.items()}
        return value

    @staticmethod
    def _desensitize_trace(trace: list[dict] | None) -> list[dict]:
        """tool_trace 字符串字段统一脱敏，与现有日志口径一致。"""
        if not trace:
            return []
        return [QueryLogStore._desensitize_value(entry) for entry in trace]

    def insert(
        self,
        *,
        user_id: int | None,
        received_at: datetime,
        original_question: str,
        rewritten_question: str | None,
        kb_id: str | None,
        question_type: str | None,
        config_snapshot: dict,
        retrieval_adapter: str | None,
        is_fallback: bool,
        max_score: float | None,
        retrieved_chunks: list,
        answer: str | None,
        citations: list,
        is_refusal: bool,
        is_stale: bool,
        graphrag_enabled: bool,
        graphrag_used: bool,
        latency_ms_rewrite: int | None,
        latency_ms_retrieve: int | None,
        latency_ms_generate: int | None,
        latency_ms_total: int | None,
        tool_trace: list | None = None,
        self_querying_dropped_fields: list[str] | None = None,
        retrieval_metadata: dict | None = None,
    ) -> QueryLog:
        original_question = self._desensitize(original_question)
        rewritten_question = self._desensitize(rewritten_question) if rewritten_question else None
        answer = self._desensitize(answer) if answer else None
        tool_trace = self._desensitize_trace(tool_trace)
        self_querying_dropped_fields = self_querying_dropped_fields or []
        retrieval_metadata = retrieval_metadata or {}

        log_hash = self._hash(
            f"{user_id}:{original_question}:{received_at.isoformat()}"
        )
        with self._session_factory() as session:
            log = QueryLog(
                log_hash=log_hash,
                user_hash=self._hash(str(user_id)) if user_id else None,
                received_at=received_at,
                original_question=original_question,
                rewritten_question=rewritten_question,
                kb_id=kb_id,
                question_type=question_type,
                config_snapshot=json.dumps(config_snapshot, ensure_ascii=False),
                retrieval_adapter=retrieval_adapter,
                is_fallback=is_fallback,
                max_score=max_score,
                retrieved_chunks=json.dumps(
                    [{"chunk_id": c.chunk_id, "source_id": c.source_id, "score": c.score} for c in retrieved_chunks],
                    ensure_ascii=False,
                ),
                answer=answer,
                citations_json=json.dumps(
                    [c.model_dump() if hasattr(c, "model_dump") else c for c in citations],
                    ensure_ascii=False,
                ),
                is_refusal=is_refusal,
                is_stale=is_stale,
                graphrag_enabled=graphrag_enabled,
                graphrag_used=graphrag_used,
                latency_ms_rewrite=latency_ms_rewrite,
                latency_ms_retrieve=latency_ms_retrieve,
                latency_ms_generate=latency_ms_generate,
                latency_ms_total=latency_ms_total,
                tool_trace=tool_trace,
                self_querying_dropped_fields=self_querying_dropped_fields,
                extra_json=retrieval_metadata,
            )
            session.add(log)
            session.commit()
            session.refresh(log)
            return log
