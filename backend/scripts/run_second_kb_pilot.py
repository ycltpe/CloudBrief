"""第二个知识库 GraphRAG 试点端到端脚本。

该脚本自动完成以下流程：
1. 在数据库中创建知识库目录与文件记录
2. 复制样本供应链文档到目录存储
3. 自动生成/确认 GraphRAG schema
4. 启用 GraphRAG
5. 同步执行单文件向量索引
6. 同步执行图索引全量重建
7. 运行 gold set 对比评估（向量 RAG vs GraphRAG）

用法：
    cd backend
    PYTHONPATH=. uv run python scripts/run_second_kb_pilot.py

注意：
- 需要已启动 Neo4j、Milvus、Redis、MySQL。
- 会消耗 DashScope API token（Embedding + LLM 抽取 + LLM 生成）。
- 脚本运行前会自动检测活跃向量索引；若不存在会先执行全量重建。
"""

import asyncio
import hashlib
import json
import re
import shutil
import uuid
from argparse import ArgumentParser
from collections import Counter
from pathlib import Path

import structlog

from app.clients.model_client import ModelClient
from app.config import get_settings
from app.models.graph_schemas import KbGraphSchema
from app.models.schemas import ChatRequest
from app.services.chat_service import ChatService
from app.services.graph_extraction import GraphExtractionService
from app.stages.chunking import ChunkingInput, ChunkingStage
from app.stores.db import init_db
from app.stores.graph_schema_store import GraphSchemaStore
from app.stores.graph_store import GraphStore
from app.stores.index_metadata import IndexMetadataStore
from app.stores.kb import KbStore
from app.tasks.indexing import index_file_task, rebuild_index_task

logger = structlog.get_logger()

GOLD_SET = [
    {
        "question": "CloudBrief 的 CEO 是谁？她直接管理哪些部门负责人？",
        "expected_entities": ["韩梅梅", "李雷", "张伟", "王芳"],
        "expected_relations": [("李雷", "汇报给", "韩梅梅"), ("张伟", "汇报给", "韩梅梅"), ("王芳", "汇报给", "韩梅梅")],
        "needs_graph": True,
    },
    {
        "question": "知识库产品的技术负责人是谁？",
        "expected_entities": ["赵敏"],
        "expected_relations": [("赵敏", "技术负责人", "CloudBrief 知识库")],
        "needs_graph": False,
    },
    {
        "question": "哪些项目依赖 DashScope？",
        "expected_entities": ["项目 Alpha", "项目 Beta", "CloudBrief 知识库", "CloudBrief 智能客服"],
        "expected_relations": [("CloudBrief 知识库", "依赖", "DashScope"), ("CloudBrief 智能客服", "依赖", "DashScope")],
        "needs_graph": True,
    },
    {
        "question": "项目 Gamma 的项目经理是谁？参与部门有哪些？",
        "expected_entities": ["陈静", "供应链管理部", "产品研发部"],
        "expected_relations": [("陈静", "项目经理", "项目 Gamma")],
        "needs_graph": True,
    },
    {
        "question": "陈静在哪些项目中担任角色？",
        "expected_entities": ["陈静", "项目 Gamma", "CloudBrief 数据分析平台"],
        "expected_relations": [("陈静", "技术负责人", "CloudBrief 数据分析平台"), ("陈静", "项目经理", "项目 Gamma")],
        "needs_graph": True,
    },
    {
        "question": "智能客服产品依赖哪些供应商？",
        "expected_entities": ["CloudBrief 智能客服", "DashScope", "讯飞星火"],
        "expected_relations": [("CloudBrief 智能客服", "依赖", "DashScope"), ("CloudBrief 智能客服", "依赖", "讯飞星火")],
        "needs_graph": True,
    },
    {
        "question": "刘洋和哪位同事共同参与 Beta 项目？",
        "expected_entities": ["刘洋", "赵敏", "项目 Beta"],
        "expected_relations": [("刘洋", "共同参与", "项目 Beta"), ("赵敏", "共同参与", "项目 Beta")],
        "needs_graph": True,
    },
    {
        "question": "数据分析平台使用哪家云服务商？",
        "expected_entities": ["CloudBrief 数据分析平台", "阿里云"],
        "expected_relations": [("CloudBrief 数据分析平台", "依赖", "阿里云")],
        "needs_graph": False,
    },
    {
        "question": "哪些产品由同一个人兼任产品负责人？请说明具体是谁。",
        "expected_entities": ["李雷", "CloudBrief 知识库", "张伟", "CloudBrief 数据分析平台", "王芳", "CloudBrief 智能客服"],
        "expected_relations": [],
        "needs_graph": True,
    },
    {
        "question": "项目 Alpha 的预计上线时间是什么时候？",
        "expected_entities": ["项目 Alpha"],
        "expected_relations": [],
        "needs_graph": False,
    },
]


def _setup_directory_and_file() -> tuple[int, int]:
    """创建或复用试点知识库目录并导入样本文件，返回 (directory_id, file_id)。"""
    settings = get_settings()
    storage_path = Path(settings.kb_storage_path)
    storage_path.mkdir(parents=True, exist_ok=True)

    kb_store = KbStore()
    schema_store = GraphSchemaStore()
    existing = None
    for d in kb_store.list_all_directories():
        if d.name == "GraphRAG 试点 - 供应链":
            existing = d
            break

    if existing:
        directory_id = existing.id
        logger.info("pilot_directory_reused", directory_id=directory_id)
        # 确保存在默认 schema 行
        if schema_store.get_by_directory_id(directory_id) is None:
            schema_store.create_default(directory_id)
    else:
        directory = kb_store.create_directory(
            name="GraphRAG 试点 - 供应链",
            description="用于验证 GraphRAG 在非样本场景下的通用性",
            created_by=None,
        )
        directory_id = directory.id
        schema_store.create_default(directory_id)
        logger.info("pilot_directory_created", directory_id=directory_id)

    # 复制样本文件到目录存储
    sample_path = Path(__file__).resolve().parents[1] / "data" / "kb" / "graphrag_pilot_supply_chain.md"
    dir_storage = storage_path / f"dir_{directory_id}"
    dir_storage.mkdir(parents=True, exist_ok=True)
    stored_name = f"graphrag_pilot_supply_chain_{uuid.uuid4().hex[:8]}.md"
    relative_path = f"dir_{directory_id}/{stored_name}"
    dest_path = storage_path / relative_path
    shutil.copy2(sample_path, dest_path)

    contents = dest_path.read_bytes()
    content_hash = hashlib.sha256(contents).hexdigest()

    # 创建文件记录
    file = kb_store.create_file(
        directory_id=directory_id,
        original_name="graphrag_pilot_supply_chain.md",
        stored_name=stored_name,
        relative_path=relative_path,
        size=len(contents),
        mime_type="text/markdown",
        created_by=None,
        content_hash=content_hash,
    )
    logger.info("pilot_file_created", directory_id=directory_id, file_id=file.id)
    return directory_id, file.id


async def _recommend_and_save_schema(directory_id: int) -> KbGraphSchema:
    """基于样本 chunks 自动生成 schema 推荐并保存。"""
    settings = get_settings()
    sample_path = Path(__file__).resolve().parents[1] / "data" / "kb" / "graphrag_pilot_supply_chain.md"
    from app.stages.parsing import NativeParser

    parser = NativeParser(sample_path.parents[1])
    documents = parser.parse_file(sample_path)

    chunking_stage = ChunkingStage()
    chunks = chunking_stage.execute(ChunkingInput(documents=documents)).chunks

    model_client = ModelClient(settings)
    try:
        service = GraphExtractionService(model_client)
        schema = await service.recommend_schema(chunks, kb_id=str(directory_id))
    finally:
        model_client.close()

    schema_store = GraphSchemaStore()
    schema.enabled = True
    schema.enabled_by_user = True
    schema_store.update_schema(
        directory_id=directory_id,
        entity_types=schema.entity_types,
        relation_types=schema.relation_types,
    )
    schema_store.set_enabled(directory_id, enabled=True)
    logger.info("pilot_schema_saved", directory_id=directory_id, entity_types=len(schema.entity_types), relation_types=len(schema.relation_types))
    return schema


def _ensure_active_index():
    """确保存在活跃向量索引；若不存在则执行全量重建。"""
    active = IndexMetadataStore().get_active()
    if active:
        return active
    logger.warning("no_active_index_rebuilding")
    rebuild_index_task.run()
    return IndexMetadataStore().get_active()


def _run_vector_index(file_id: int):
    """同步执行单文件向量索引。"""
    logger.info("pilot_vector_index_start", file_id=file_id)
    result = index_file_task.run(file_id=file_id)
    logger.info("pilot_vector_index_done", file_id=file_id, result=result)
    return result


async def _run_graph_build(directory_id: int):
    """直接执行图索引全量重建核心逻辑（避免 Celery 任务内 asyncio.run 冲突）。"""
    from app.services.graph_extraction import GraphExtractionService
    from app.stores.graph_schema_store import GraphSchemaStore
    from app.stores.graph_store import GraphStore
    from app.stores.index_metadata import IndexMetadataStore
    from app.stores.milvus import MilvusStore

    logger.info("pilot_graph_build_start", directory_id=directory_id)
    settings = get_settings()

    schema = GraphSchemaStore().get_by_directory_id(directory_id)
    if not schema or not schema.enabled:
        logger.warning("pilot_graph_build_skipped_not_enabled", directory_id=directory_id)
        return {"skipped": True, "kb_id": str(directory_id)}

    active = IndexMetadataStore().get_active()
    if not active:
        raise ValueError("NO_ACTIVE_INDEX")

    milvus_store = MilvusStore(settings.milvus_uri, active.collection_name)
    all_chunks = [chunk for chunk, _ in milvus_store.get_all_chunks()]
    prefix = f"kb/dir_{directory_id}/"
    kb_chunks = [c for c in all_chunks if c.source_id.startswith(prefix)]

    if not kb_chunks:
        logger.warning("pilot_graph_build_no_chunks", directory_id=directory_id)
        return {"skipped": True, "kb_id": str(directory_id), "chunks": 0}

    model_client = ModelClient(settings)
    try:
        service = GraphExtractionService(model_client)
        extraction_result = await service.extract(kb_chunks, schema=schema, kb_id=str(directory_id))
    finally:
        model_client.close()

    graph_store = await GraphStore.create()
    try:
        if not graph_store.is_available:
            raise RuntimeError("Neo4j 不可用")
        await graph_store.initialize_schema()
        await graph_store.clear_kb(str(directory_id))
        await graph_store.upsert_entities(extraction_result.entities, str(directory_id))
        await graph_store.upsert_relations(extraction_result.relations, str(directory_id))
    finally:
        await graph_store.close()

    GraphSchemaStore().record_build(
        directory_id=directory_id,
        entities=len(extraction_result.entities),
        relations=len(extraction_result.relations),
        diagnostics=extraction_result.diagnostics,
    )

    result = {
        "kb_id": str(directory_id),
        "entities": len(extraction_result.entities),
        "relations": len(extraction_result.relations),
    }
    logger.info("pilot_graph_build_done", directory_id=directory_id, result=result)
    return result


async def _answer_vector_only(question: str) -> str:
    """仅使用向量 RAG 回答问题。"""
    service = ChatService(graph_store=None)
    try:
        response = await service.ask(ChatRequest(question=question))
        return response.answer
    finally:
        service.model_client.close()


async def _answer_with_graph(question: str, entity_names: list[str] | None = None) -> tuple[str, dict]:
    """使用向量 RAG + GraphRAG 回答问题；可传入已知实体名以绕过 LLM 实体链接。"""
    from app.pipelines.generation import GenerationPipeline, GenerationPipelineInput
    from app.pipelines.retrieval import RetrievalPipeline
    from app.stages.graph_rag_context_stage import GraphRAGContextStage

    settings = get_settings()
    graph_store = await GraphStore.create()
    model_client = ModelClient(settings)
    try:
        retrieval = RetrievalPipeline(model_client)
        generation = GenerationPipeline(model_client, graph_store=graph_store)

        retrieval_output = retrieval.retrieve(question)
        retrieval_results = retrieval_output.results
        is_fallback = retrieval_output.is_fallback

        # 推导 kb_id
        pattern = re.compile(r"^kb/dir_(\d+)/")
        matches = [m.group(1) for c in retrieval_results for m in [pattern.match(c.source_id)] if m]
        kb_id = Counter(matches).most_common(1)[0][0] if matches else None

        # 获取图谱上下文
        graph_context = None
        if kb_id and entity_names:
            schema = GraphSchemaStore().get_by_directory_id(int(kb_id))
            stage = GraphRAGContextStage(graph_store, model_client=model_client)
            try:
                graph_context = await stage.run(
                    question=question,
                    kb_id=kb_id,
                    schema=schema,
                    entity_names=entity_names,
                )
            except Exception as exc:
                logger.warning("pilot_manual_graph_context_failed", error=str(exc))

        gen_input = GenerationPipelineInput(
            question=question,
            chunks=retrieval_results,
            max_score=max((r.score for r in retrieval_results), default=0.0),
            is_fallback=is_fallback,
            kb_id=kb_id,
            graph_context=graph_context,
        )
        output = await generation.generate(gen_input)
        return output.answer, output.diagnostics
    finally:
        model_client.close()
        await graph_store.close()


async def _evaluate_subgraph_recall(directory_id: int) -> dict:
    """直接评估子图召回率，不依赖 LLM 答案生成。"""
    from app.stages.graph_rag_context_stage import GraphRAGContextStage

    graph_store = await GraphStore.create()
    try:
        schema = GraphSchemaStore().get_by_directory_id(directory_id)
        if not schema or not schema.enabled:
            raise ValueError("GRAPH_RAG_NOT_ENABLED")

        stage = GraphRAGContextStage(graph_store, model_client=None)
        results = []
        for item in GOLD_SET:
            entity_names = item["expected_entities"]
            context = await stage.run(
                question=item["question"],
                kb_id=str(directory_id),
                schema=schema,
                entity_names=entity_names,
                max_hops=2,
                max_nodes=30,
            )
            returned_entities = {e.name for e in context.entities}

            entity_hits = sum(1 for e in entity_names if e in returned_entities)
            relation_hits = 0
            for source, rel_type, target in item["expected_relations"]:
                if source in returned_entities and target in returned_entities:
                    relation_hits += 1

            results.append({
                "question": item["question"],
                "entity_recall": entity_hits / len(entity_names) if entity_names else 1.0,
                "relation_recall": relation_hits / len(item["expected_relations"]) if item["expected_relations"] else 1.0,
                "returned_entity_count": len(context.entities),
                "returned_relation_count": len(context.relations),
            })

        def _avg(key: str) -> float:
            values = [r[key] for r in results]
            return sum(values) / len(values) if values else 0.0

        return {
            "avg_entity_recall": _avg("entity_recall"),
            "avg_relation_recall": _avg("relation_recall"),
            "details": results,
        }
    finally:
        await graph_store.close()


def _evaluate_answer(answer: str, expected_entities: list[str], expected_relations: list[tuple]) -> dict:
    """简单评估：检查答案中是否包含期望实体与关系。"""
    entity_hits = sum(1 for e in expected_entities if e in answer)
    relation_hits = 0
    for source, rel_type, target in expected_relations:
        if source in answer and target in answer:
            relation_hits += 1

    return {
        "entity_recall": entity_hits / len(expected_entities) if expected_entities else 1.0,
        "relation_recall": relation_hits / len(expected_relations) if expected_relations else 1.0,
        "entity_hits": entity_hits,
        "entity_total": len(expected_entities),
        "relation_hits": relation_hits,
        "relation_total": len(expected_relations),
    }


async def main(skip_build: bool = False, recall_only: bool = False):
    init_db()
    directory_id, file_id = _setup_directory_and_file()

    if not skip_build:
        logger.info("pilot_schema_recommend_start", directory_id=directory_id)
        schema = await _recommend_and_save_schema(directory_id)

        _ensure_active_index()
        _run_vector_index(file_id)
        graph_result = await _run_graph_build(directory_id)

        if graph_result.get("skipped"):
            logger.warning("pilot_graph_build_skipped", result=graph_result)
            return
    else:
        logger.info("pilot_skip_build", directory_id=directory_id)
        schema = GraphSchemaStore().get_by_directory_id(directory_id)
        if not schema:
            raise ValueError("SCHEMA_NOT_FOUND_FOR_EVAL_ONLY")
        graph_result = {"kb_id": str(directory_id), "skipped": True, "note": "skip_build mode"}

    if recall_only:
        logger.info("pilot_recall_only_eval_start", directory_id=directory_id)
        recall_report = await _evaluate_subgraph_recall(directory_id)
        output_path = Path(__file__).resolve().parents[1] / "data" / f"second_kb_pilot_recall_report_{directory_id}.json"
        output_path.write_text(json.dumps(recall_report, ensure_ascii=False, indent=2))
        logger.info("pilot_recall_report_saved", path=str(output_path))

        print("\n===== 第二个知识库 GraphRAG 子图召回评估报告 =====")
        print(f"知识库 ID: {directory_id}")
        print(f"Gold set 问题数: {len(GOLD_SET)}")
        print(f"平均实体召回: {recall_report['avg_entity_recall']:.2%}")
        print(f"平均关系召回: {recall_report['avg_relation_recall']:.2%}")
        print(f"详细报告: {output_path}")
        return

    # 对比评估
    vector_scores = []
    graph_scores = []
    detailed = []

    for item in GOLD_SET:
        question = item["question"]
        expected_entities = item["expected_entities"]
        expected_relations = item["expected_relations"]

        logger.info("pilot_eval_question", question=question)

        vector_answer = await _answer_vector_only(question)
        graph_answer, _ = await _answer_with_graph(question, entity_names=expected_entities)

        vector_metrics = _evaluate_answer(vector_answer, expected_entities, expected_relations)
        graph_metrics = _evaluate_answer(graph_answer, expected_entities, expected_relations)

        vector_scores.append(vector_metrics)
        graph_scores.append(graph_metrics)

        detailed.append({
            "question": question,
            "needs_graph": item["needs_graph"],
            "vector_answer": vector_answer,
            "graph_answer": graph_answer,
            "vector_metrics": vector_metrics,
            "graph_metrics": graph_metrics,
        })

    def _avg(key: str, scores: list[dict]) -> float:
        values = [s[key] for s in scores]
        return sum(values) / len(values) if values else 0.0

    report = {
        "directory_id": directory_id,
        "file_id": file_id,
        "schema": {
            "entity_types": [et.name for et in schema.entity_types],
            "relation_types": [rt.name for rt in schema.relation_types],
        },
        "graph_build": graph_result,
        "summary": {
            "vector_entity_recall": _avg("entity_recall", vector_scores),
            "vector_relation_recall": _avg("relation_recall", vector_scores),
            "graph_entity_recall": _avg("entity_recall", graph_scores),
            "graph_relation_recall": _avg("relation_recall", graph_scores),
            "question_count": len(GOLD_SET),
        },
        "detailed": detailed,
    }

    output_path = Path(__file__).resolve().parents[1] / "data" / f"second_kb_pilot_report_{directory_id}.json"
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    logger.info("pilot_report_saved", path=str(output_path))

    print("\n===== 第二个知识库 GraphRAG 试点评估报告 =====")
    print(f"知识库 ID: {directory_id}")
    print(f"Gold set 问题数: {report['summary']['question_count']}")
    print(f"向量 RAG 实体召回: {report['summary']['vector_entity_recall']:.2%}")
    print(f"向量 RAG 关系召回: {report['summary']['vector_relation_recall']:.2%}")
    print(f"GraphRAG 实体召回: {report['summary']['graph_entity_recall']:.2%}")
    print(f"GraphRAG 关系召回: {report['summary']['graph_relation_recall']:.2%}")
    print(f"详细报告: {output_path}")


if __name__ == "__main__":
    parser = ArgumentParser(description="第二个知识库 GraphRAG 试点")
    parser.add_argument("--skip-build", action="store_true", help="跳过 schema、向量索引、图构建，仅运行评估")
    parser.add_argument("--recall-only", action="store_true", help="仅评估子图召回率，不调用 LLM 生成答案")
    args = parser.parse_args()
    asyncio.run(main(skip_build=args.skip_build, recall_only=args.recall_only))
