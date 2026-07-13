"""GraphRAG Phase 1 PoC 脚本：构建图并对比 向量 RAG vs GraphRAG。

运行方式（在 backend/ 目录下）：
    uv run python scripts/build_graph_poc.py

前置条件：
    1. .env 中 DASHSCOPE_API_KEY 有效。
    2. Neo4j 已启动（docker compose up -d neo4j）。
    3. 已安装 graphrag 可选依赖（uv sync --extra graphrag）。
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

# 图抽取请求较大，DashScope 响应较慢，临时提升超时
os.environ.setdefault("REQUEST_TIMEOUT", "300")
os.environ.setdefault("LLM_MODEL", "qwen3.7-plus")

# 允许脚本从 backend/ 目录运行时导入 app.*
BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from app.clients.model_client import ModelClient  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.models.graph_schemas import (  # noqa: E402
    Entity,
    EntityType,
    GraphExtractionResult,
    KbGraphSchema,
    Relation,
    RelationType,
    SubgraphContext,
)
from app.services.graph_extraction import GraphExtractionService  # noqa: E402
from app.stages.base import Chunk, Document  # noqa: E402
from app.stages.chunking import ChunkingInput, ChunkingStage  # noqa: E402
from app.stages.graph_rag_context_stage import GraphRAGContextStage  # noqa: E402
from app.stores.graph_store import GraphStore  # noqa: E402

# 允许通过环境变量切换启发式抽取，避免 API 不稳定时阻塞 PoC
USE_HEURISTIC_EXTRACTION = os.environ.get("GRAPH_POC_HEURISTIC", "1") == "1"

logger = None  # 使用 print，避免 structlog 配置

POC_DATA_DIR = Path(__file__).resolve().parents[2] / "_bmad-output" / "specs" / "spec-cloudbrief-graphrag" / "poc-data"
REPORT_DIR = Path(__file__).resolve().parents[2] / "_bmad-output" / "specs" / "spec-cloudbrief-graphrag"
EXTRACTION_CACHE_PATH = REPORT_DIR / "poc-extraction-cache.json"
KB_ID = "poc-cloudbrief"

# 为 PoC 预定义 schema，降低 LLM 抽取方差
POC_SCHEMA = KbGraphSchema(
    kb_id=KB_ID,
    enabled=True,
    enabled_by_user=True,
    entity_types=[
        EntityType(name="人员", description="公司内外的自然人", examples=["王建国", "张伟"]),
        EntityType(name="部门", description="公司内部的组织单元", examples=["产品技术中心", "销售部"]),
        EntityType(name="公司", description="企业或机构", examples=["云景科技", "星辰云"]),
        EntityType(name="职位", description="岗位或职务", examples=["CEO", "CTO"]),
        EntityType(name="产品/服务", description="软件、平台或服务", examples=["协同平台", "CDN"]),
    ],
    relation_types=[
        RelationType(name="担任", source_types=["人员"], target_types=["职位"]),
        RelationType(name="负责", source_types=["人员"], target_types=["部门"]),
        RelationType(name="汇报给", source_types=["人员"], target_types=["人员"]),
        RelationType(name="曾任职于", source_types=["人员"], target_types=["公司"]),
        RelationType(name="任职于", source_types=["人员"], target_types=["公司"]),
        RelationType(name="包含", source_types=["部门"], target_types=["部门"]),
        RelationType(name="供应商", source_types=["公司"], target_types=["公司"]),
        RelationType(name="客户", source_types=["公司"], target_types=["公司"]),
        RelationType(name="代理", source_types=["公司"], target_types=["公司"]),
        RelationType(name="使用", source_types=["公司"], target_types=["产品/服务"]),
    ],
)


def load_documents() -> list[Document]:
    docs: list[Document] = []
    for file_path in sorted(POC_DATA_DIR.glob("sample_*.md")):
        content = file_path.read_text(encoding="utf-8")
        docs.append(
            Document(
                content=content,
                source_type="poc_doc",
                title=file_path.stem,
                updated_at=datetime.utcnow(),
                source_id=file_path.name,
            )
        )
    return docs


def load_gold_set() -> list[dict[str, Any]]:
    path = POC_DATA_DIR / "gold_set.json"
    return json.loads(path.read_text(encoding="utf-8"))


def load_cached_extraction() -> GraphExtractionResult | None:
    if not EXTRACTION_CACHE_PATH.exists():
        return None
    data = json.loads(EXTRACTION_CACHE_PATH.read_text(encoding="utf-8"))
    return GraphExtractionResult(
        entities=[Entity(**e) for e in data.get("entities", [])],
        relations=[Relation(**r) for r in data.get("relations", [])],
        diagnostics=data.get("diagnostics", {}),
    )


def save_cached_extraction(result: GraphExtractionResult) -> None:
    EXTRACTION_CACHE_PATH.write_text(
        json.dumps(
            {
                "entities": [e.model_dump() for e in result.entities],
                "relations": [r.model_dump() for r in result.relations],
                "diagnostics": result.diagnostics,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def make_chunks(docs: list[Document]) -> list[Chunk]:
    stage = ChunkingStage(max_chars=800, overlap_chars=80)
    output = stage.execute(ChunkingInput(documents=docs))
    return output.chunks


def simple_keyword_retrieve(question: str, chunks: list[Chunk], top_k: int = 5) -> list[Chunk]:
    """简单的关键词重叠检索，用于 PoC 基线。"""
    keywords = set(question) - set("。？，！、；：\""'（）《》【】')
    scored: list[tuple[float, Chunk]] = []
    for chunk in chunks:
        score = sum(1 for kw in keywords if kw in chunk.content)
        scored.append((score, chunk))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [c for _, c in scored[:top_k]]


def format_chunks(chunks: list[Chunk]) -> str:
    return "\n\n".join(
        f"[{chunk.chunk_id}] {chunk.title}\n{chunk.content}" for chunk in chunks
    )


async def answer_with_chunks(
    model_client: ModelClient,
    question: str,
    chunks: list[Chunk],
) -> tuple[str, float]:
    """仅使用 chunks 回答，返回答案与耗时（毫秒）。"""
    evidence = format_chunks(chunks)
    messages = [
        {
            "role": "system",
            "content": (
                "你是一个严谨的内部支持助手。你只能基于下面给出的证据回答问题。"
                "如果证据不足以回答，请直接回复：根据当前知识库，我找不到足够信息回答这个问题。"
                "保持简洁、分点说明。"
            ),
        },
        {"role": "user", "content": f"证据：\n\n{evidence}\n\n用户问题：{question}\n\n请用中文回答。"},
    ]
    start = time.perf_counter()
    answer = await model_client.chat(messages, stream=False, temperature=0.1)
    latency_ms = (time.perf_counter() - start) * 1000
    return answer, latency_ms


async def answer_with_graphrag(
    model_client: ModelClient,
    graph_stage: GraphRAGContextStage,
    question: str,
    chunks: list[Chunk],
) -> tuple[str, SubgraphContext, float]:
    """使用 chunks + 子图上下文回答，返回答案、子图上下文与耗时（毫秒）。"""
    subgraph = await graph_stage.run(
        question=question,
        kb_id=KB_ID,
        schema=POC_SCHEMA,
        max_hops=2,
        max_nodes=20,
    )
    evidence = format_chunks(chunks)
    graph_text = subgraph.text
    if graph_text:
        evidence = f"{evidence}\n\n{graph_text}"

    messages = [
        {
            "role": "system",
            "content": (
                "你是一个严谨的内部支持助手。你只能基于下面给出的证据（包括文本片段和图谱上下文）回答问题。"
                "如果证据不足以回答，请直接回复：根据当前知识库，我找不到足够信息回答这个问题。"
                "保持简洁、分点说明。"
            ),
        },
        {"role": "user", "content": f"证据：\n\n{evidence}\n\n用户问题：{question}\n\n请用中文回答。"},
    ]
    start = time.perf_counter()
    answer = await model_client.chat(messages, stream=False, temperature=0.1)
    latency_ms = (time.perf_counter() - start) * 1000
    return answer, subgraph, latency_ms


async def judge_answer(
    model_client: ModelClient,
    question: str,
    ground_truth: str,
    answer: str,
) -> dict[str, Any]:
    """使用 LLM 判断答案质量。"""
    prompt = f"""请判断以下答案是否准确回答了问题。要求：
1. 如果答案与参考答案在关键事实上不一致，判为 incorrect。
2. 如果答案缺少关键信息导致无法完整回答问题，判为 partial。
3. 如果答案基本正确且覆盖关键信息，判为 correct。
4. 简要说明理由。

问题：{question}
参考答案：{ground_truth}
待判答案：{answer}

请只输出 JSON，不要包含 markdown 代码块或其他说明：{{"verdict": "correct|partial|incorrect", "reason": "..."}}"""

    response = await model_client.chat(
        messages=[{"role": "user", "content": prompt}],
        stream=False,
        temperature=0.1,
    )
    cleaned = _extract_json_object(response)
    try:
        data = json.loads(cleaned)
        if isinstance(data, dict):
            return {
                "verdict": data.get("verdict", "unknown"),
                "reason": data.get("reason", ""),
            }
    except Exception:
        pass
    # 兜底：按关键词粗略判断
    if "找不到足够信息" in answer or "无法确定" in answer:
        return {"verdict": "incorrect", "reason": f"答案未找到信息； judge raw: {response[:200]}"}
    # 简单包含判断
    gt_keywords = [w for w in ground_truth if len(w) >= 2]
    hit = sum(1 for w in gt_keywords if w in answer)
    if hit >= max(1, len(gt_keywords) * 0.5):
        return {"verdict": "correct", "reason": f"关键词覆盖； judge raw: {response[:200]}"}
    return {"verdict": "partial", "reason": f"关键词覆盖不足； judge raw: {response[:200]}"}


def _extract_json_object(text: str) -> str:
    """从文本中提取第一个 JSON 对象。"""
    # 去除 markdown 代码块
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    text = text.strip()
    # 尝试直接解析
    try:
        json.loads(text)
        return text
    except Exception:
        pass
    # 找第一个 { 和最后一个 }
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return text[start : end + 1]
    return text


async def main() -> None:
    print("=" * 60)
    print("CloudBrief GraphRAG Phase 1 PoC")
    print("=" * 60)

    settings = get_settings()
    if not settings.dashscope_api_key.get_secret_value():
        print("错误：DASHSCOPE_API_KEY 未配置")
        sys.exit(1)

    # 图抽取使用轻量模型加速，答案生成使用配置模型
    extraction_settings = settings.model_copy(update={"llm_model": "qwen2.5-7b-instruct"})
    extraction_client = ModelClient(extraction_settings)
    model_client = ModelClient(settings)
    graph_store = await GraphStore.create()
    if not graph_store.is_available:
        print("警告：Neo4j 未连接，GraphRAG 对比将跳过")
    else:
        await graph_store.initialize_schema()
        await graph_store.clear_kb(KB_ID)
        print(f"已清空知识库 {KB_ID} 的图数据")

    extraction_service = GraphExtractionService(extraction_client)
    graph_stage = GraphRAGContextStage(graph_store, model_client)

    docs = load_documents()
    chunks = make_chunks(docs)
    print(f"加载 {len(docs)} 篇文档，切分为 {len(chunks)} 个 chunk")

    # 抽取并写入图（支持缓存，避免 API 不稳定时重复抽取）
    cached = load_cached_extraction()
    extraction_ms = 0.0
    if cached:
        print(f"从缓存加载抽取结果：{len(cached.entities)} 个实体，{len(cached.relations)} 条关系")
        extraction_result = cached
    elif USE_HEURISTIC_EXTRACTION:
        print("使用启发式抽取（跳过 LLM，用于快速验证管线）…")
        from scripts.heuristic_extraction import extract as heuristic_extract
        extraction_start = time.perf_counter()
        extraction_result = heuristic_extract(chunks, KB_ID)
        extraction_ms = (time.perf_counter() - extraction_start) * 1000
        print(
            f"抽取完成：{len(extraction_result.entities)} 个实体，"
            f"{len(extraction_result.relations)} 条关系，耗时 {extraction_ms:.0f} ms"
        )
        save_cached_extraction(extraction_result)
    else:
        print("开始 LLM 抽取实体与关系…")
        extraction_start = time.perf_counter()
        extraction_result = await extraction_service.extract(chunks, POC_SCHEMA, kb_id=KB_ID)
        extraction_ms = (time.perf_counter() - extraction_start) * 1000
        print(
            f"抽取完成：{len(extraction_result.entities)} 个实体，"
            f"{len(extraction_result.relations)} 条关系，耗时 {extraction_ms:.0f} ms"
        )
        save_cached_extraction(extraction_result)

    if graph_store.is_available:
        await graph_store.upsert_entities(extraction_result.entities, KB_ID)
        await graph_store.upsert_relations(extraction_result.relations, KB_ID)
        print("图数据已写入 Neo4j")

    # 评估
    gold_set = load_gold_set()
    print(f"加载 gold set：{len(gold_set)} 个问题")

    results: list[dict[str, Any]] = []
    baseline_correct = 0
    graphrag_correct = 0
    total_baseline_ms = 0.0
    total_graphrag_ms = 0.0
    total_graphrag_extraction_ms = 0.0

    for idx, item in enumerate(gold_set, 1):
        question = item["question"]
        ground_truth = item["answer"]
        category = item.get("category", "未分类")
        retrieved = simple_keyword_retrieve(question, chunks, top_k=5)

        baseline_answer, baseline_ms = await answer_with_chunks(model_client, question, retrieved)
        total_baseline_ms += baseline_ms

        if graph_store.is_available:
            graph_start = time.perf_counter()
            graphrag_answer, subgraph, graphrag_answer_ms = await answer_with_graphrag(
                model_client, graph_stage, question, retrieved
            )
            graphrag_total_ms = (time.perf_counter() - graph_start) * 1000
            total_graphrag_ms += graphrag_total_ms
            total_graphrag_extraction_ms += graphrag_total_ms - graphrag_answer_ms
        else:
            graphrag_answer = baseline_answer
            subgraph = None

        baseline_judge = await judge_answer(model_client, question, ground_truth, baseline_answer)
        graphrag_judge = await judge_answer(model_client, question, ground_truth, graphrag_answer)

        if baseline_judge["verdict"] == "correct":
            baseline_correct += 1
        if graphrag_judge["verdict"] == "correct":
            graphrag_correct += 1

        result_item = {
            "idx": idx,
            "category": category,
            "question": question,
            "ground_truth": ground_truth,
            "baseline": {
                "answer": baseline_answer,
                "latency_ms": round(baseline_ms, 2),
                "verdict": baseline_judge["verdict"],
                "reason": baseline_judge["reason"],
            },
            "graphrag": {
                "answer": graphrag_answer,
                "latency_ms": round(total_graphrag_ms / idx if graph_store.is_available else baseline_ms, 2),
                "verdict": graphrag_judge["verdict"],
                "reason": graphrag_judge["reason"],
                "subgraph": {
                    "entity_count": len(subgraph.entities) if subgraph else 0,
                    "relation_count": len(subgraph.relations) if subgraph else 0,
                    "text": subgraph.text if subgraph else "",
                    "diagnostics": subgraph.diagnostics if subgraph else {},
                },
            },
        }
        results.append(result_item)
        print(f"[{idx}/{len(gold_set)}] {question}")
        print(f"  基线: {baseline_judge['verdict']} | GraphRAG: {graphrag_judge['verdict']}")

    # 指标汇总
    baseline_accuracy = baseline_correct / len(gold_set) if gold_set else 0
    graphrag_accuracy = graphrag_correct / len(gold_set) if gold_set else 0
    avg_baseline_ms = total_baseline_ms / len(gold_set) if gold_set else 0
    avg_graphrag_ms = total_graphrag_ms / len(gold_set) if gold_set else 0
    overhead_ratio = (
        (avg_graphrag_ms - avg_baseline_ms) / avg_baseline_ms if avg_baseline_ms > 0 else 0
    )

    metrics = {
        "sample_kb_id": KB_ID,
        "document_count": len(docs),
        "chunk_count": len(chunks),
        "entity_count": len(extraction_result.entities),
        "relation_count": len(extraction_result.relations),
        "extraction_latency_ms": round(extraction_ms, 2),
        "question_count": len(gold_set),
        "baseline": {
            "correct": baseline_correct,
            "accuracy": round(baseline_accuracy, 4),
            "avg_latency_ms": round(avg_baseline_ms, 2),
        },
        "graphrag": {
            "correct": graphrag_correct,
            "accuracy": round(graphrag_accuracy, 4),
            "avg_latency_ms": round(avg_graphrag_ms, 2),
            "avg_extraction_overhead_ms": round(
                total_graphrag_extraction_ms / len(gold_set) if gold_set else 0, 2
            ),
            "overhead_ratio": round(overhead_ratio, 4),
        },
        "results": results,
    }

    report_path = REPORT_DIR / "poc-report.json"
    report_path.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n" + "=" * 60)
    print("评估结果")
    print("=" * 60)
    print(f"文档数: {len(docs)} | Chunk 数: {len(chunks)}")
    print(f"抽取实体: {len(extraction_result.entities)} | 关系: {len(extraction_result.relations)}")
    print(f"基线准确率: {baseline_accuracy:.1%} ({baseline_correct}/{len(gold_set)})")
    print(f"GraphRAG 准确率: {graphrag_accuracy:.1%} ({graphrag_correct}/{len(gold_set)})")
    print(f"基线平均耗时: {avg_baseline_ms:.0f} ms")
    print(f"GraphRAG 平均耗时: {avg_graphrag_ms:.0f} ms")
    print(f"GraphRAG 额外开销比例: {overhead_ratio:.1%}")
    print(f"详细报告: {report_path}")

    await extraction_client.aclose()
    await model_client.aclose()
    await graph_store.close()


if __name__ == "__main__":
    asyncio.run(main())
