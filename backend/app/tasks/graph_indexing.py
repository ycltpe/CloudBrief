import asyncio
import uuid

import redis
import structlog

from app.celery_app import celery_app
from app.clients.model_client import ModelClient
from app.config import get_settings
from app.models.graph_schemas import KbGraphSchema
from app.services.graph_extraction import GraphExtractionService
from app.services.settings_service import SettingsService
from app.stores.graph_schema_store import GraphSchemaStore
from app.stores.graph_store import GraphStore
from app.stores.index_metadata import IndexMetadataStore
from app.stores.milvus import MilvusStore
from app.tasks.indexing import _publish_step, _run_step

logger = structlog.get_logger()


def _get_redis_client():
    return redis.from_url(SettingsService().get_runtime_value("redis_url"))


def _load_schema(kb_id: str) -> KbGraphSchema | None:
    directory_id = int(kb_id)
    store = GraphSchemaStore()
    return store.get_by_directory_id(directory_id)


def _filter_kb_chunks(chunks, kb_id: str):
    prefix = f"kb/dir_{kb_id}/"
    return [c for c in chunks if c.source_id.startswith(prefix)]


@celery_app.task(bind=True, max_retries=0)
def rebuild_graph_task(self, kb_id: str):
    task_id = self.request.id or str(uuid.uuid4())
    settings = get_settings()
    redis_client = _get_redis_client()

    _publish_step(redis_client, task_id, "task", "running", log=f"开始重建知识库 {kb_id} 的图索引")

    try:
        schema = _load_schema(kb_id)
        if not schema or not schema.enabled:
            _publish_step(redis_client, task_id, "task", "completed", log="GraphRAG 未启用，跳过")
            return {"skipped": True, "kb_id": kb_id}

        active = IndexMetadataStore().get_active()
        if not active:
            raise ValueError("NO_ACTIVE_INDEX")

        milvus_store = MilvusStore(SettingsService().get_runtime_value("milvus_uri"), active.collection_name)

        def _load_chunks():
            return [chunk for chunk, _ in milvus_store.get_all_chunks()]

        all_chunks = _run_step(
            redis_client,
            task_id,
            "graph_load_chunks",
            _load_chunks,
            log_on_complete=lambda chunks: f"加载 {len(chunks)} 个 chunk",
        )

        kb_chunks = _filter_kb_chunks(all_chunks, kb_id)
        if not kb_chunks:
            _publish_step(redis_client, task_id, "task", "completed", log="该知识库下没有 chunk")
            return {"skipped": True, "kb_id": kb_id, "chunks": 0}

        model_client = ModelClient(settings)
        try:
            extraction_service = GraphExtractionService(model_client)

            async def _extract():
                return await extraction_service.extract(kb_chunks, schema=schema, kb_id=kb_id)

            extraction_result = _run_step(
                redis_client,
                task_id,
                "graph_extraction",
                lambda: asyncio.run(_extract()),
                log_on_complete=lambda result: f"抽取完成：{len(result.entities)} 个实体，{len(result.relations)} 个关系",
            )
        finally:
            model_client.close()

        # 抽取质量告警检查
        _check_extraction_quality(kb_id, extraction_result)

        async def _write_graph():
            graph_store = await GraphStore.create()
            if not graph_store.is_available:
                raise RuntimeError("Neo4j 不可用")
            await graph_store.initialize_schema()
            await graph_store.clear_kb(kb_id)
            await graph_store.upsert_entities(extraction_result.entities, kb_id)
            await graph_store.upsert_relations(extraction_result.relations, kb_id)
            await graph_store.close()
            return len(extraction_result.entities), len(extraction_result.relations)

        entity_count, relation_count = _run_step(
            redis_client,
            task_id,
            "graph_building",
            lambda: asyncio.run(_write_graph()),
            log_on_complete=lambda counts: f"写入图数据库：{counts[0]} 个实体，{counts[1]} 个关系",
        )

        _publish_step(
            redis_client,
            task_id,
            "graph_indexing_complete",
            "completed",
            log=f"图索引构建完成：{entity_count} 个实体，{relation_count} 个关系",
        )
        _publish_step(
            redis_client,
            task_id,
            "task",
            "completed",
            log=f"知识库 {kb_id} 图索引重建完成",
        )

        try:
            GraphSchemaStore().record_build(
                directory_id=int(kb_id),
                task_id=task_id,
                entities=entity_count,
                relations=relation_count,
                diagnostics=extraction_result.diagnostics,
            )
        except Exception as exc:
            logger.warning("record_graph_build_failed", kb_id=kb_id, task_id=task_id, error=str(exc))

        return {
            "kb_id": kb_id,
            "entities": entity_count,
            "relations": relation_count,
        }
    except Exception as exc:
        error_msg = str(exc)
        _publish_step(redis_client, task_id, "task", "failed", log=error_msg)
        logger.error("rebuild_graph_task_failed", task_id=task_id, kb_id=kb_id, error=error_msg)
        try:
            GraphSchemaStore().record_build(
                directory_id=int(kb_id),
                task_id=task_id,
                error=error_msg,
            )
        except Exception:
            pass
        raise


@celery_app.task(bind=True, max_retries=0)
def index_file_graph_task(self, kb_id: str, doc_id: str):
    """为单个文档执行图索引增量更新：删除旧 doc 图数据并写入新抽取结果。"""
    task_id = self.request.id or str(uuid.uuid4())
    settings = get_settings()
    redis_client = _get_redis_client()

    _publish_step(
        redis_client,
        task_id,
        "task",
        "running",
        log=f"开始增量更新知识库 {kb_id} 文档 {doc_id} 的图索引",
    )

    try:
        schema = _load_schema(kb_id)
        if not schema or not schema.enabled:
            _publish_step(redis_client, task_id, "task", "completed", log="GraphRAG 未启用，跳过")
            return {"skipped": True, "kb_id": kb_id, "doc_id": doc_id}

        active = IndexMetadataStore().get_active()
        if not active:
            raise ValueError("NO_ACTIVE_INDEX")

        milvus_store = MilvusStore(SettingsService().get_runtime_value("milvus_uri"), active.collection_name)

        def _load_doc_chunks():
            all_chunks = [chunk for chunk, _ in milvus_store.get_all_chunks()]
            return [c for c in all_chunks if c.source_id == doc_id]

        doc_chunks = _run_step(
            redis_client,
            task_id,
            "graph_load_chunks",
            _load_doc_chunks,
            log_on_complete=lambda chunks: f"加载文档 {doc_id} 的 {len(chunks)} 个 chunk",
        )

        if not doc_chunks:
            _publish_step(
                redis_client,
                task_id,
                "task",
                "completed",
                log=f"文档 {doc_id} 下没有 chunk",
            )
            return {"skipped": True, "kb_id": kb_id, "doc_id": doc_id, "chunks": 0}

        model_client = ModelClient(settings)
        try:
            extraction_service = GraphExtractionService(model_client)

            async def _extract():
                return await extraction_service.extract(doc_chunks, schema=schema, kb_id=kb_id)

            extraction_result = _run_step(
                redis_client,
                task_id,
                "graph_extraction",
                lambda: asyncio.run(_extract()),
                log_on_complete=lambda result: f"抽取完成：{len(result.entities)} 个实体，{len(result.relations)} 个关系",
            )
        finally:
            model_client.close()

        # 抽取质量告警检查
        _check_extraction_quality(kb_id, extraction_result)

        async def _write_graph():
            graph_store = await GraphStore.create()
            if not graph_store.is_available:
                raise RuntimeError("Neo4j 不可用")
            await graph_store.initialize_schema()
            deletion_stats = await graph_store.delete_entities_and_relations_by_doc(kb_id, doc_id)
            await graph_store.upsert_entities(extraction_result.entities, kb_id)
            await graph_store.upsert_relations(extraction_result.relations, kb_id)
            await graph_store.close()
            return deletion_stats, len(extraction_result.entities), len(extraction_result.relations)

        deletion_stats, entity_count, relation_count = _run_step(
            redis_client,
            task_id,
            "graph_building",
            lambda: asyncio.run(_write_graph()),
            log_on_complete=lambda result: (
                f"写入图数据库：删除 {result[0]['deleted_entities']} 个旧实体，"
                f"新增/更新 {result[1]} 个实体，{result[2]} 个关系"
            ),
        )

        _publish_step(
            redis_client,
            task_id,
            "graph_indexing_complete",
            "completed",
            log=f"图索引增量更新完成：{entity_count} 个实体，{relation_count} 个关系",
        )
        _publish_step(
            redis_client,
            task_id,
            "task",
            "completed",
            log=f"知识库 {kb_id} 文档 {doc_id} 图索引增量更新完成",
        )

        try:
            GraphSchemaStore().record_build(
                directory_id=int(kb_id),
                task_id=task_id,
                entities=entity_count,
                relations=relation_count,
                diagnostics={"doc_id": doc_id, **extraction_result.diagnostics},
            )
        except Exception as exc:
            logger.warning("record_graph_build_failed", kb_id=kb_id, task_id=task_id, doc_id=doc_id, error=str(exc))

        return {
            "kb_id": kb_id,
            "doc_id": doc_id,
            "deleted": deletion_stats,
            "entities": entity_count,
            "relations": relation_count,
        }
    except Exception as exc:
        error_msg = str(exc)
        _publish_step(redis_client, task_id, "task", "failed", log=error_msg)
        logger.error(
            "index_file_graph_task_failed",
            task_id=task_id,
            kb_id=kb_id,
            doc_id=doc_id,
            error=error_msg,
        )
        try:
            GraphSchemaStore().record_build(
                directory_id=int(kb_id),
                task_id=task_id,
                error=error_msg,
            )
        except Exception:
            pass
        raise


def _check_extraction_quality(kb_id: str, extraction_result) -> None:
    """检查抽取质量并输出结构化告警日志。"""
    from app.models.graph_schemas import GraphExtractionResult
    from app.services.settings_service import SettingsService

    if not isinstance(extraction_result, GraphExtractionResult):
        return

    settings_service = SettingsService()
    min_entities = settings_service.get_runtime_value("graphrag_min_extraction_entities")
    entity_count = len(extraction_result.entities)
    relation_count = len(extraction_result.relations)
    parse_errors = extraction_result.diagnostics.get("parse_errors", 0)

    if entity_count < min_entities:
        logger.warning(
            "graph_extraction_quality_alert",
            kb_id=kb_id,
            reason="too_few_entities",
            entity_count=entity_count,
            threshold=min_entities,
        )
    if parse_errors > 0:
        logger.warning(
            "graph_extraction_quality_alert",
            kb_id=kb_id,
            reason="parse_errors",
            parse_errors=parse_errors,
            entity_count=entity_count,
            relation_count=relation_count,
        )
