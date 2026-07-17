"""CloudBrief RAGAS 双路径评测入口。

支持 pipeline（原生检索+生成）与 agentic（plan/grade/多跳）两种模式，以及
`--mode both` 一次性跑双路径并输出对照报告。报告包含 Story 3.5 要求的：
- 多跳样本通过率
- 低质用例拒答准确率
- 单跳 P50 延迟增幅
- 单跳平均 token/请求增幅（多跳样本除外）

用法：
    uv run python -m eval.run_eval --mode both
"""

import argparse
import asyncio
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from app.clients.model_client import ModelClient
from app.config import get_settings
from app.orchestration import AgentGraphRunner, AgenticGraphDeps
from app.pipelines.generation import GenerationPipeline, GenerationPipelineInput
from app.pipelines.retrieval import RetrievalPipeline
from app.stages.grade import GradeStage
from app.stages.multi_hop_decompose import MultiHopDecomposeStage
from app.stages.plan import PlanStage
from app.stages.query_rewrite import QueryRewriteStage
from app.stores.eval_results import EvalResultStore
from app.stores.graph_schema_store import GraphSchemaStore
from eval.comparison import compare, summarize
from eval.metrics import (
    LLMJudgeMetrics,
    citation_accuracy,
    hit_rate,
    refusal_accuracy,
    stale_accuracy,
)

DEFAULT_KB_ID = "default"
DEFAULT_TOP_K = 50
DEFAULT_TOP_N = 5


def load_eval_set(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        return data
    return data.get("items", [])


def _contexts_from_results(results: list[Any]) -> list[dict[str, Any]]:
    """把检索结果对象转换为可序列化的上下文字典列表。"""
    contexts: list[dict[str, Any]] = []
    for result in results:
        if isinstance(result, dict):
            contexts.append(result)
        elif hasattr(result, "model_dump"):
            contexts.append(result.model_dump())
        else:
            contexts.append({"repr": str(result)})
    return contexts


def _empty_scores(should_refuse: bool, should_stale: bool) -> dict[str, Any]:
    return {
        "hit_rate": 0.0,
        "citation_accuracy": 0.0,
        "refusal_accuracy": refusal_accuracy(should_refuse, False),
        "stale_accuracy": stale_accuracy(should_stale, False),
        "context_relevance": 0.0,
        "context_precision": 0.0,
        "context_recall": 0.0,
        "faithfulness": 0.0,
        "answer_relevance": 0.0,
        "latency_ms": 0,
    }


async def evaluate_one(
    item: dict[str, Any],
    model_client: ModelClient,
    mode: str,
    judge: LLMJudgeMetrics,
) -> dict[str, Any]:
    question = item["question"]
    category = item.get("category", "direct")
    expected_chunk_ids = item.get("expected_chunk_ids", [])
    should_refuse = item.get("should_refuse", False)
    should_stale = item.get("should_stale", False)
    kb_id = item.get("kb_id", DEFAULT_KB_ID)

    start = time.perf_counter()

    try:
        if mode == "pipeline":
            retrieval_pipeline = RetrievalPipeline(model_client)
            generation_pipeline = GenerationPipeline(model_client)
            retrieval_output = await asyncio.to_thread(
                retrieval_pipeline.retrieve,
                question,
                DEFAULT_TOP_K,
                DEFAULT_TOP_N,
                kb_id,
            )
            results = retrieval_output.results
            max_score = max((r.score for r in results), default=0.0)
            gen_output = await generation_pipeline.generate(
                GenerationPipelineInput(
                    question=question,
                    chunks=results,
                    max_score=max_score,
                    is_fallback=retrieval_output.is_fallback,
                    history=[],
                    kb_id=kb_id,
                )
            )
            answer = gen_output.answer
            citations = [c.model_dump() for c in gen_output.citations]
            is_refusal = gen_output.is_refusal
            is_stale = gen_output.is_stale
            total_tokens = gen_output.tokens_used or {}
            contexts = _contexts_from_results(results)
            retrieved_ids = [r.chunk_id for r in results]
        else:
            graph_schema_store = GraphSchemaStore()
            deps = AgenticGraphDeps(
                retrieval_pipeline=RetrievalPipeline(model_client),
                generation_pipeline=GenerationPipeline(model_client),
                query_rewrite_stage=QueryRewriteStage(),
                grade_stage=GradeStage(model_client),
                plan_stage=PlanStage(model_client, graph_schema_store),
                multi_hop_decompose_stage=MultiHopDecomposeStage(model_client),
            )
            runner = AgentGraphRunner(deps)
            async for _event in runner.stream(
                {
                    "question": question,
                    "conversation_id": None,
                    "history": [],
                    "kb_id": kb_id,
                }
            ):
                pass
            final = runner.final_state
            answer = final.get("answer", "")
            citations = final.get("citations", [])
            is_refusal = final.get("is_refusal", False)
            is_stale = final.get("is_stale", False)
            total_tokens = final.get("token_usage", {})
            retrieval_results = final.get("retrieval_results", [])
            contexts = _contexts_from_results(retrieval_results)
            retrieved_ids = [r.chunk_id for r in retrieval_results]

        latency_ms = int((time.perf_counter() - start) * 1000)

        context_texts = [c.get("content", "") for c in contexts]
        context_relevance, context_precision, faithfulness, answer_relevance = (
            await asyncio.gather(
                judge.context_relevance(question, context_texts),
                judge.context_precision(question, context_texts, expected_chunk_ids),
                judge.faithfulness(answer, context_texts),
                judge.answer_relevance(question, answer),
            )
        )
        context_recall = judge.context_recall(
            question, context_texts, expected_chunk_ids
        )

        scores = {
            "hit_rate": hit_rate(retrieved_ids, expected_chunk_ids),
            "citation_accuracy": citation_accuracy(
                answer, citations, expected_chunk_ids
            ),
            "refusal_accuracy": refusal_accuracy(should_refuse, is_refusal),
            "stale_accuracy": stale_accuracy(should_stale, is_stale),
            "context_relevance": context_relevance,
            "context_precision": context_precision,
            "context_recall": context_recall,
            "faithfulness": faithfulness,
            "answer_relevance": answer_relevance,
            "latency_ms": latency_ms,
        }

        total = sum(total_tokens.values()) if total_tokens else 0

        return {
            "id": item["id"],
            "question": question,
            "category": category,
            "answer": answer,
            "contexts": contexts,
            "scores": scores,
            "total_tokens": total,
            "is_refusal": is_refusal,
            "is_stale": is_stale,
            "expected_chunk_ids": expected_chunk_ids,
        }
    except Exception as exc:
        return {
            "id": item["id"],
            "question": question,
            "category": category,
            "answer": "",
            "contexts": [],
            "scores": _empty_scores(should_refuse, should_stale),
            "total_tokens": 0,
            "is_refusal": False,
            "is_stale": False,
            "expected_chunk_ids": expected_chunk_ids,
            "error": str(exc),
        }


async def main():
    parser = argparse.ArgumentParser(description="CloudBrief RAGAS 双路径评测")
    parser.add_argument(
        "--mode",
        choices=["pipeline", "agentic", "both"],
        default="both",
        help="评测模式：pipeline、agentic 或 both（对照）",
    )
    parser.add_argument(
        "--eval-set",
        default="eval/eval_set_v2.json",
        help="评测集路径（相对 backend/）",
    )
    args = parser.parse_args()

    settings = get_settings()
    model_client = ModelClient(settings)
    eval_store = EvalResultStore()
    judge = LLMJudgeMetrics(model_client)

    eval_path = Path(__file__).resolve().parent / args.eval_set
    eval_set = load_eval_set(eval_path)

    pipeline_results: list[dict[str, Any]] = []
    agentic_results: list[dict[str, Any]] = []

    if args.mode in ("pipeline", "both"):
        for item in eval_set:
            print(f"Evaluating [pipeline] {item['id']}...")
            try:
                result = await evaluate_one(item, model_client, "pipeline", judge)
                pipeline_results.append(result)
                eval_store.create(
                    question=item["question"],
                    contexts=result["contexts"],
                    answer=result["answer"],
                    ground_truth="\n".join(item.get("expected_answer_points", [])),
                    ragas_scores=result["scores"],
                    reasoning={
                        "mode": "pipeline",
                        "expected_chunk_ids": result["expected_chunk_ids"],
                        "is_refusal": result["is_refusal"],
                        "is_stale": result["is_stale"],
                        "total_tokens": result["total_tokens"],
                        "category": result["category"],
                    },
                )
            except Exception as exc:
                print(f"Failed [pipeline] {item['id']}: {exc}")
                pipeline_results.append(
                    {
                        "id": item["id"],
                        "question": item["question"],
                        "error": str(exc),
                        "category": item.get("category", "direct"),
                    }
                )

    if args.mode in ("agentic", "both"):
        for item in eval_set:
            print(f"Evaluating [agentic] {item['id']}...")
            try:
                result = await evaluate_one(item, model_client, "agentic", judge)
                agentic_results.append(result)
                eval_store.create(
                    question=item["question"],
                    contexts=result["contexts"],
                    answer=result["answer"],
                    ground_truth="\n".join(item.get("expected_answer_points", [])),
                    ragas_scores=result["scores"],
                    reasoning={
                        "mode": "agentic",
                        "expected_chunk_ids": result["expected_chunk_ids"],
                        "is_refusal": result["is_refusal"],
                        "is_stale": result["is_stale"],
                        "total_tokens": result["total_tokens"],
                        "category": result["category"],
                    },
                )
            except Exception as exc:
                print(f"Failed [agentic] {item['id']}: {exc}")
                agentic_results.append(
                    {
                        "id": item["id"],
                        "question": item["question"],
                        "error": str(exc),
                        "category": item.get("category", "direct"),
                    }
                )

    model_client.close()

    report: dict[str, Any] = {
        "created_at": datetime.utcnow().isoformat(),
        "mode": args.mode,
    }
    if pipeline_results:
        report["pipeline"] = {
            "summary": summarize(pipeline_results),
            "results": pipeline_results,
        }
    if agentic_results:
        report["agentic"] = {
            "summary": summarize(agentic_results),
            "results": agentic_results,
        }
    if pipeline_results and agentic_results:
        report["comparison"] = compare(pipeline_results, agentic_results)

    report_path = (
        Path(__file__).resolve().parent
        / f"report_{args.mode}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.json"
    )
    with report_path.open("w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print("\n=== Evaluation Summary ===")
    if "comparison" in report:
        print(json.dumps(report["comparison"], ensure_ascii=False, indent=2))
    else:
        print(
            json.dumps(
                report.get("pipeline", report.get("agentic", {})).get(
                    "summary", {}
                ),
                ensure_ascii=False,
                indent=2,
            )
        )
    print(f"\nReport saved to: {report_path}")


if __name__ == "__main__":
    asyncio.run(main())
