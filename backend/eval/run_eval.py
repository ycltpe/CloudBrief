import asyncio
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from app.clients.model_client import ModelClient
from app.config import get_settings
from app.pipelines.generation import GenerationPipeline, GenerationPipelineInput
from app.pipelines.retrieval import RetrievalPipeline
from app.stores.eval_results import EvalResultStore
from eval.metrics import (
    LLMJudgeMetrics,
    citation_accuracy,
    hit_rate,
    refusal_accuracy,
    stale_accuracy,
)


def load_eval_set(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


async def evaluate_one(item: dict[str, Any], model_client: ModelClient) -> dict[str, Any]:
    retrieval = RetrievalPipeline(model_client)
    generation = GenerationPipeline(model_client)
    judge = LLMJudgeMetrics(model_client)

    start = time.perf_counter()
    retrieved = retrieval.retrieve(item["question"])
    retrieved_ids = [r.chunk_id for r in retrieved]
    max_score = max((r.score for r in retrieved), default=0.0)

    gen_output = await generation.generate(
        GenerationPipelineInput(
            question=item["question"],
            chunks=retrieved,
            max_score=max_score,
        )
    )
    latency_ms = int((time.perf_counter() - start) * 1000)

    contexts = [r.content for r in retrieved]
    expected_ids = item.get("expected_chunk_ids", [])

    (
        context_relevance,
        context_precision,
        faithfulness_score,
        answer_relevance_score,
    ) = await asyncio.gather(
        judge.context_relevance(item["question"], contexts),
        judge.context_precision(item["question"], contexts, expected_ids),
        judge.faithfulness(gen_output.answer, contexts),
        judge.answer_relevance(item["question"], gen_output.answer),
    )

    scores = {
        "hit_rate": hit_rate(retrieved_ids, expected_ids),
        "citation_accuracy": citation_accuracy(
            gen_output.answer,
            [c.model_dump() for c in gen_output.citations],
            expected_ids,
        ),
        "refusal_accuracy": refusal_accuracy(
            item.get("should_refuse", False),
            gen_output.is_refusal,
        ),
        "stale_accuracy": stale_accuracy(
            item.get("should_stale", False),
            gen_output.is_stale,
        ),
        "context_relevance": context_relevance,
        "context_precision": context_precision,
        "context_recall": judge.context_recall(item["question"], contexts, expected_ids),
        "faithfulness": faithfulness_score,
        "answer_relevance": answer_relevance_score,
        "latency_ms": latency_ms,
    }

    return {
        "id": item["id"],
        "question": item["question"],
        "answer": gen_output.answer,
        "is_refusal": gen_output.is_refusal,
        "is_stale": gen_output.is_stale,
        "contexts": [
            {
                "chunk_id": r.chunk_id,
                "title": r.title,
                "source_type": r.source_type,
                "content": r.content,
                "score": r.score,
            }
            for r in retrieved
        ],
        "scores": scores,
        "expected_chunk_ids": expected_ids,
    }


async def main():
    settings = get_settings()
    model_client = ModelClient(settings)
    eval_store = EvalResultStore()

    eval_path = Path(__file__).resolve().parent / "eval_set.json"
    eval_set = load_eval_set(eval_path)

    results: list[dict[str, Any]] = []
    for item in eval_set:
        print(f"Evaluating {item['id']}...")
        try:
            result = await evaluate_one(item, model_client)
            results.append(result)

            eval_store.create(
                question=item["question"],
                contexts=result["contexts"],
                answer=result["answer"],
                ground_truth="\n".join(item.get("expected_answer_points", [])),
                ragas_scores=result["scores"],
                reasoning={
                    "expected_chunk_ids": result["expected_chunk_ids"],
                    "is_refusal": result["is_refusal"],
                    "is_stale": result["is_stale"],
                },
            )
        except Exception as exc:
            print(f"Failed {item['id']}: {exc}")
            results.append(
                {
                    "id": item["id"],
                    "question": item["question"],
                    "error": str(exc),
                }
            )

    model_client.close()

    # 汇总
    score_keys = [
        "hit_rate",
        "citation_accuracy",
        "refusal_accuracy",
        "stale_accuracy",
        "context_relevance",
        "context_precision",
        "context_recall",
        "faithfulness",
        "answer_relevance",
    ]
    summary: dict[str, Any] = {}
    for key in score_keys:
        values = [r["scores"][key] for r in results if "scores" in r and key in r["scores"]]
        summary[key] = round(sum(values) / len(values), 4) if values else 0.0

    latencies = [r["scores"]["latency_ms"] for r in results if "scores" in r]
    summary["latency_p50_ms"] = sorted(latencies)[len(latencies) // 2] if latencies else 0
    summary["latency_p90_ms"] = sorted(latencies)[int(len(latencies) * 0.9)] if latencies else 0

    report = {
        "created_at": datetime.utcnow().isoformat(),
        "summary": summary,
        "results": results,
    }

    report_path = Path(__file__).resolve().parent / f"report_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.json"
    with report_path.open("w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print("\n=== Evaluation Summary ===")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"\nReport saved to: {report_path}")


if __name__ == "__main__":
    asyncio.run(main())
