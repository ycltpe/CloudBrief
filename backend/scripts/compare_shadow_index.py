"""Shadow 索引对照分析 CLI。

用法示例：
    cd backend
    uv run python scripts/compare_shadow_index.py \
        --kb_id default \
        --questions "如何导出报表" "登录失败怎么办" \
        --top_k 50 \
        --top_n 5

输出指标：
    - 召回重叠率（主索引 Top-N 与 Shadow 索引 Top-N 的 chunk_id 交集）
    - 主索引 / Shadow 索引的 P50/P95 延迟
    - Top-5 召回差异样本
"""

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

# 允许直接运行 scripts/ 下的脚本：把项目根目录加入模块搜索路径
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from app.clients.model_client import ModelClient  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.services.settings_service import SettingsService  # noqa: E402
from app.stages.vector_retrieval import VectorRetrievalInput, VectorRetrievalStage  # noqa: E402
from app.stores.index_metadata import IndexMetadataStore  # noqa: E402
from app.stores.milvus import MilvusStore  # noqa: E402


def _now_ms() -> int:
    return int(time.perf_counter() * 1000)


def _run_query(model_client, settings_service, active, question: str, top_k: int, top_n: int):
    runtime_embedding_model = settings_service.get_runtime_value("embedding_model")
    primary_collection = active.collection_name
    shadow_collection = getattr(active, "shadow_collection_name", None)
    shadow_index_type = getattr(active, "shadow_index_type", None)

    # 主索引向量检索
    primary_start = time.perf_counter()
    primary_store = MilvusStore(settings_service.get_runtime_value("milvus_uri"), primary_collection)
    primary_stage = VectorRetrievalStage(model_client, primary_store)
    primary_results = primary_stage.execute(
        VectorRetrievalInput(query=question, top_k=top_k),
        model_name=runtime_embedding_model,
    ).results
    primary_latency_ms = int((time.perf_counter() - primary_start) * 1000)

    # Shadow 索引向量检索
    shadow_results = []
    shadow_latency_ms = None
    shadow_error = None
    if shadow_collection and shadow_index_type:
        try:
            shadow_start = time.perf_counter()
            shadow_store = MilvusStore(
                settings_service.get_runtime_value("milvus_uri"),
                shadow_collection,
                index_type=shadow_index_type,
            )
            shadow_stage = VectorRetrievalStage(model_client, shadow_store)
            shadow_results = shadow_stage.execute(
                VectorRetrievalInput(query=question, top_k=top_k),
                model_name=runtime_embedding_model,
            ).results
            shadow_latency_ms = int((time.perf_counter() - shadow_start) * 1000)
        except Exception as exc:
            shadow_error = str(exc)

    primary_topn_ids = {r.chunk_id for r in primary_results[:top_n]}
    shadow_topn_ids = {r.chunk_id for r in shadow_results[:top_n]}
    overlap = primary_topn_ids & shadow_topn_ids
    overlap_ratio = len(overlap) / top_n if top_n > 0 else 0.0

    return {
        "question": question,
        "primary_latency_ms": primary_latency_ms,
        "shadow_latency_ms": shadow_latency_ms,
        "shadow_error": shadow_error,
        "primary_topn_ids": list(primary_topn_ids),
        "shadow_topn_ids": list(shadow_topn_ids),
        "overlap_ids": list(overlap),
        "overlap_ratio": overlap_ratio,
        "primary_only_ids": list(primary_topn_ids - shadow_topn_ids),
        "shadow_only_ids": list(shadow_topn_ids - primary_topn_ids),
    }


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    sorted_values = sorted(values)
    k = (len(sorted_values) - 1) * p / 100
    f = int(k)
    c = min(f + 1, len(sorted_values) - 1)
    if f == c:
        return sorted_values[f]
    return sorted_values[f] * (c - k) + sorted_values[c] * (k - f)


def main():
    parser = argparse.ArgumentParser(description="对比主索引与 Shadow 索引的召回与延迟")
    parser.add_argument("--kb_id", default="default", help="知识库 ID")
    parser.add_argument("--questions", nargs="+", required=True, help="待测问题列表")
    parser.add_argument("--top_k", type=int, default=50, help="向量召回数量")
    parser.add_argument("--top_n", type=int, default=5, help="参与对比的 Top-N 数量")
    args = parser.parse_args()

    settings = get_settings()
    model_client = ModelClient(settings)
    settings_service = SettingsService()
    metadata_store = IndexMetadataStore()

    active = metadata_store.get_active(args.kb_id)
    if not active:
        print(f"错误：知识库 {args.kb_id} 没有活跃索引", file=sys.stderr)
        sys.exit(1)

    shadow_collection = getattr(active, "shadow_collection_name", None)
    shadow_index_type = getattr(active, "shadow_index_type", None)
    if not shadow_collection or not shadow_index_type:
        print(
            f"警告：知识库 {args.kb_id} 当前没有 Shadow 索引（主索引 {active.collection_name}，类型 {active.index_type}）",
            file=sys.stderr,
        )

    rows = []
    for question in args.questions:
        result = _run_query(model_client, settings_service, active, question, args.top_k, args.top_n)
        rows.append(result)

    primary_latencies = [r["primary_latency_ms"] for r in rows]
    shadow_latencies = [r["shadow_latency_ms"] for r in rows if r["shadow_latency_ms"] is not None]
    overlap_ratios = [r["overlap_ratio"] for r in rows]

    stats = {
        "kb_id": args.kb_id,
        "primary_index": {
            "collection_name": active.collection_name,
            "index_type": active.index_type,
        },
        "shadow_index": {
            "collection_name": shadow_collection,
            "index_type": shadow_index_type,
        },
        "query_count": len(rows),
        "overlap": {
            "mean": round(statistics.mean(overlap_ratios), 3) if overlap_ratios else 0.0,
            "min": round(min(overlap_ratios), 3) if overlap_ratios else 0.0,
            "max": round(max(overlap_ratios), 3) if overlap_ratios else 0.0,
        },
        "primary_latency_ms": {
            "p50": _percentile(primary_latencies, 50),
            "p95": _percentile(primary_latencies, 95),
            "mean": round(statistics.mean(primary_latencies), 1) if primary_latencies else 0.0,
        },
        "shadow_latency_ms": {
            "p50": _percentile(shadow_latencies, 50),
            "p95": _percentile(shadow_latencies, 95),
            "mean": round(statistics.mean(shadow_latencies), 1) if shadow_latencies else 0.0,
        },
        "samples": rows,
    }

    print(json.dumps(stats, ensure_ascii=False, indent=2))
    model_client.close()


if __name__ == "__main__":
    main()
