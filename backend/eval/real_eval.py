import asyncio
import json
import random
from datetime import datetime, timedelta
from typing import Any

from app.clients.model_client import ModelClient
from app.config import get_settings
from app.stores.db import QueryLog, get_session_factory
from app.stores.eval_results import EvalResultStore
from eval.metrics import LLMJudgeMetrics


class RealQueryEvaluator:
    """从真实用户查询日志中采样并执行 LLM-as-judge 自动评估。"""

    def __init__(self, model_client: ModelClient | None = None):
        self.settings = get_settings()
        self.model_client = model_client or ModelClient(self.settings)
        self.judge = LLMJudgeMetrics(self.model_client)
        self.eval_store = EvalResultStore()
        self._session_factory = get_session_factory()

    def sample_logs(
        self,
        start: datetime,
        end: datetime,
        limit: int = 100,
        random_seed: int = 42,
    ) -> list[QueryLog]:
        """按时间范围随机采样 query_logs。"""
        with self._session_factory() as session:
            query = (
                session.query(QueryLog)
                .filter(QueryLog.received_at >= start, QueryLog.received_at < end)
            )
            rows = query.all()
            if len(rows) <= limit:
                return rows
            random.seed(random_seed)
            return random.sample(rows, limit)

    async def evaluate_one(self, log: QueryLog) -> dict[str, Any] | None:
        """对单条 query_log 执行自动评估。"""
        try:
            contexts = self._parse_retrieved_chunks(log.retrieved_chunks)
            answer = log.answer or ""
            question = log.original_question

            context_relevance, faithfulness_score, answer_relevance_score = await asyncio.gather(
                self.judge.context_relevance(question, contexts),
                self.judge.faithfulness(answer, contexts),
                self.judge.answer_relevance(question, answer),
            )

            scores = {
                "context_relevance": context_relevance,
                "faithfulness": faithfulness_score,
                "answer_relevance": answer_relevance_score,
                "is_refusal": log.is_refusal,
                "is_stale": log.is_stale,
                "is_fallback": log.is_fallback,
                "latency_ms_total": log.latency_ms_total,
            }

            self.eval_store.create(
                question=question,
                contexts=contexts,
                answer=answer,
                ground_truth=None,
                ragas_scores=scores,
                reasoning={
                    "query_log_id": log.id,
                    "kb_id": log.kb_id,
                    "config_snapshot": log.config_snapshot,
                    "retrieval_adapter": log.retrieval_adapter,
                    "max_score": log.max_score,
                },
            )

            return {
                "query_log_id": log.id,
                "question": question,
                "answer": answer,
                "scores": scores,
            }
        except Exception as exc:
            logger = __import__("structlog").get_logger()
            logger.warning("real_eval_one_failed", query_log_id=log.id, error=str(exc))
            return None

    @staticmethod
    def _parse_retrieved_chunks(raw: str | None) -> list[str]:
        if not raw:
            return []
        try:
            data = json.loads(raw)
            return [item.get("content", "") for item in data if isinstance(item, dict)]
        except Exception:
            return []

    async def run(
        self,
        days: int = 7,
        sample_size: int = 100,
    ) -> dict[str, Any]:
        """执行一周真实查询的自动评估。"""
        end = datetime.utcnow()
        start = end - timedelta(days=days)
        logs = self.sample_logs(start, end, limit=sample_size)

        results = []
        for log in logs:
            result = await self.evaluate_one(log)
            if result:
                results.append(result)

        summary = self._summarize(results)
        return {
            "start": start.isoformat(),
            "end": end.isoformat(),
            "sampled": len(logs),
            "evaluated": len(results),
            "summary": summary,
            "results": results,
        }

    @staticmethod
    def _summarize(results: list[dict[str, Any]]) -> dict[str, float]:
        keys = ["context_relevance", "faithfulness", "answer_relevance"]
        summary: dict[str, float] = {}
        for key in keys:
            values = [r["scores"][key] for r in results if key in r.get("scores", {})]
            summary[key] = round(sum(values) / len(values), 4) if values else 0.0

        refusal_count = sum(1 for r in results if r["scores"].get("is_refusal"))
        stale_count = sum(1 for r in results if r["scores"].get("is_stale"))
        fallback_count = sum(1 for r in results if r["scores"].get("is_fallback"))
        total = len(results) or 1
        summary["refusal_rate"] = round(refusal_count / total, 4)
        summary["stale_rate"] = round(stale_count / total, 4)
        summary["fallback_rate"] = round(fallback_count / total, 4)
        return summary

    def close(self) -> None:
        self.model_client.close()


async def run_real_eval(days: int = 7, sample_size: int = 100) -> dict[str, Any]:
    evaluator = RealQueryEvaluator()
    try:
        return await evaluator.run(days=days, sample_size=sample_size)
    finally:
        evaluator.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="真实用户查询自动评估")
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--sample-size", type=int, default=100)
    args = parser.parse_args()

    report = asyncio.run(run_real_eval(days=args.days, sample_size=args.sample_size))
    print(json.dumps(report, ensure_ascii=False, indent=2))
