import json
import time
import uuid
from datetime import datetime
from pathlib import Path

import redis
import structlog

from app.celery_app import celery_app
from app.clients.model_client import ModelClient
from app.config import get_settings
from app.metrics import INDEX_TASK_TOTAL
from app.services.settings_service import SettingsService
from app.stages.base import Chunk, Document
from app.stages.chunking import ChunkingInput, ChunkingStage
from app.stages.embedding import EmbeddingInput, EmbeddingStage
from app.stages.parsing import build_parser
from app.stores.bm25_store import BM25Store
from app.stores.index_metadata import IndexMetadataStore
from app.stores.kb import KbStore
from app.stores.milvus import MilvusStore

logger = structlog.get_logger()


def _get_redis_client():
    return redis.from_url(get_settings().redis_url)


def _publish_step(
    redis_client: redis.Redis,
    task_id: str,
    step_name: str,
    status: str,
    duration_ms: int | None = None,
    log: str | None = None,
) -> None:
    """发布任务步骤事件：持久化到 MySQL，并推送 Redis Pub/Sub 供 SSE 实时消费。"""
    from app.stores.index_task_step import IndexTaskStepStore

    timestamp = datetime.utcnow().isoformat()
    try:
        step = IndexTaskStepStore().upsert_step(
            task_id=task_id,
            step_name=step_name,
            status=status,
            duration_ms=duration_ms,
            log=log,
        )
        timestamp = step.updated_at.isoformat()
    except Exception as exc:
        logger.warning(
            "index_task_step_persist_failed",
            task_id=task_id,
            step=step_name,
            error=str(exc),
        )

    event = {
        "task_id": task_id,
        "step": step_name,
        "status": status,
        "duration_ms": duration_ms,
        "log": log,
        "timestamp": timestamp,
    }
    channel = f"index:task:{task_id}"
    try:
        redis_client.publish(channel, json.dumps(event, ensure_ascii=False))
    except Exception as exc:
        logger.warning(
            "index_task_step_publish_failed",
            task_id=task_id,
            step=step_name,
            error=str(exc),
        )


def _make_heartbeat(
    redis_client: redis.Redis,
    task_id: str,
    step_name: str,
    min_interval_seconds: float = 2.0,
):
    """返回节流心跳函数：同一步骤内的高频进度更新按间隔丢弃，末次（done>=total）必发。"""
    state = {"last": 0.0}

    def beat(log: str, done: int, total: int) -> None:
        now = time.monotonic()
        if done < total and now - state["last"] < min_interval_seconds:
            return
        state["last"] = now
        _publish_step(redis_client, task_id, step_name, "running", log=log)

    return beat


def _run_step(
    redis_client: redis.Redis,
    task_id: str,
    step_name: str,
    func,
    log_on_complete=None,
):
    _publish_step(redis_client, task_id, step_name, "running")
    start = time.perf_counter()
    try:
        result = func()
        duration_ms = int((time.perf_counter() - start) * 1000)
        log = f"{step_name} completed"
        if log_on_complete:
            try:
                log = log_on_complete(result)
            except Exception:
                pass
        _publish_step(
            redis_client,
            task_id,
            step_name,
            "completed",
            duration_ms=duration_ms,
            log=log,
        )
        return result
    except Exception as exc:
        duration_ms = int((time.perf_counter() - start) * 1000)
        _publish_step(
            redis_client,
            task_id,
            step_name,
            "failed",
            duration_ms=duration_ms,
            log=str(exc),
        )
        raise


def _parse_documents(
    kb_id: str = "default",
    on_progress=None,
    model_client=None,
) -> tuple[list[Document], list[str]]:
    """解析知识库文档，返回 (文档列表, 解析失败被跳过的文件原因列表)。"""
    settings = get_settings()
    data_dir = Path(__file__).resolve().parents[2] / "data"
    parser = build_parser(settings, data_dir, model_client=model_client)

    if kb_id == "default":
        documents = parser.parse(on_progress=on_progress)
    else:
        # 非默认知识库：只解析该顶层目录下的后台上传文件
        kb_dir = data_dir / "kb" / f"dir_{kb_id}"
        documents = parser._parse_kb(kb_dir, on_progress=on_progress) if kb_dir.exists() else []
    return documents, list(getattr(parser, "parse_errors", []))


@celery_app.task(bind=True, max_retries=0)
def rebuild_index_task(self, kb_id: str = "default"):
    task_id = self.request.id or str(uuid.uuid4())
    settings = get_settings()
    redis_client = _get_redis_client()

    _publish_step(redis_client, task_id, "task", "running", log=f"开始重建知识库 {kb_id} 索引")

    model_client = ModelClient(settings)
    settings_service = SettingsService()
    runtime_embedding_model = settings_service.get_runtime_value("embedding_model")
    runtime_embedding_dim = settings_service.get_runtime_value("embedding_dim")
    try:
        # 1. 解析（大 PDF 页级心跳 + 失败文件跳过并计数）
        parse_beat = _make_heartbeat(redis_client, task_id, "parse")
        documents, parse_errors = _run_step(
            redis_client,
            task_id,
            "parse",
            lambda: _parse_documents(
                kb_id,
                on_progress=lambda name, done, total: parse_beat(
                    f"解析 {name}：{done}/{total} 页", done, total
                ),
                model_client=model_client,
            ),
            log_on_complete=lambda result: (
                f"解析完成：{len(result[0])} 个文档"
                + (
                    f"，跳过 {len(result[1])} 个失败文件（{'; '.join(result[1][:3])}）"
                    if result[1]
                    else ""
                )
            ),
        )
        if not documents:
            # 全灭重建不得产出空索引：中止任务，原活跃索引保持不变
            raise ValueError(
                "未解析到任何有效文档，已中止重建（原索引保持不变）"
                + (f"。失败文件：{'; '.join(parse_errors[:3])}" if parse_errors else "")
            )

        # 2. 切分
        chunking_stage = ChunkingStage()
        chunking_output = _run_step(
            redis_client,
            task_id,
            "chunking",
            lambda: chunking_stage.execute(ChunkingInput(documents=documents)),
            log_on_complete=lambda out: f"文本切分完成：{len(out.chunks)} 个 chunk",
        )
        chunks = chunking_output.chunks

        # 3. Embedding（按批心跳，避免大库长时间无反馈）
        embedding_stage = EmbeddingStage(model_client, settings=settings)
        embed_beat = _make_heartbeat(redis_client, task_id, "embedding")
        embedding_output = _run_step(
            redis_client,
            task_id,
            "embedding",
            lambda: embedding_stage.execute(
                EmbeddingInput(chunks=chunks),
                model_name=runtime_embedding_model,
                on_progress=lambda done, total: embed_beat(
                    f"Embedding 进度：{done}/{total}", done, total
                ),
            ),
            log_on_complete=lambda out: f"Embedding 生成完成：{len(out.embeddings)} 条向量",
        )
        embeddings = embedding_output.embeddings

        # 4-6. 写入 Milvus、重建 BM25、原子切换需在互斥锁内完成
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        collection_name = f"{settings.milvus_collection}_kb_{kb_id}_{timestamp}_{uuid.uuid4().hex[:8]}"
        bm25_path = Path(settings.bm25_index_path).parent / f"bm25_kb_{kb_id}_{timestamp}_{uuid.uuid4().hex[:8]}.pkl"
        metadata_store = IndexMetadataStore()
        milvus_store = MilvusStore(settings.milvus_uri, collection_name, dim=runtime_embedding_dim)
        bm25_store = BM25Store(bm25_path)

        lock = redis_client.lock(
            f"index:active_switch_lock:{kb_id}",
            timeout=3600,
            blocking_timeout=300,
        )
        try:
            with lock:
                def _write_milvus():
                    milvus_store.create_collection()
                    milvus_store.insert_chunks(chunks, [e.embedding for e in embeddings])
                    return milvus_store

                _run_step(
                    redis_client,
                    task_id,
                    "write_milvus",
                    _write_milvus,
                    log_on_complete=lambda store: f"写入 Milvus 完成：{len(chunks)} 条向量写入 {store.collection_name}",
                )

                def _build_bm25():
                    bm25_store.build_index(chunks)
                    bm25_store.save()
                    return bm25_store

                _run_step(
                    redis_client,
                    task_id,
                    "build_bm25",
                    _build_bm25,
                    log_on_complete=lambda store: f"BM25 索引构建完成：{store.index_path}",
                )

                def _atomic_switch():
                    metadata_store.switch_active(
                        collection_name=collection_name,
                        bm25_index_path=str(bm25_path),
                        kb_id=kb_id,
                        reason="rebuild",
                    )

                _run_step(
                    redis_client,
                    task_id,
                    "atomic_switch",
                    _atomic_switch,
                    log_on_complete=lambda _: "索引原子切换完成，新索引已生效",
                )
        except redis.exceptions.LockError as exc:
            _publish_step(redis_client, task_id, "atomic_switch", "failed", log=f"获取索引锁超时: {exc}")
            raise

        _publish_step(
            redis_client,
            task_id,
            "task",
            "completed",
            log=f"索引切换完成：collection={collection_name}, bm25={bm25_path}",
        )
        INDEX_TASK_TOTAL.labels(task_type="rebuild", kb_id=kb_id, status="completed").inc()
        return {
            "collection_name": collection_name,
            "bm25_index_path": str(bm25_path),
            "kb_id": kb_id,
        }
    except Exception:
        INDEX_TASK_TOTAL.labels(task_type="rebuild", kb_id=kb_id, status="failed").inc()
        raise
    finally:
        model_client.close()


@celery_app.task(bind=True, max_retries=0)
def index_file_task(self, file_id: int):
    """为单个知识库文件构建索引，并原子合并到当前活跃索引（copy-on-write）。"""
    task_id = self.request.id or str(uuid.uuid4())
    settings = get_settings()
    redis_client = _get_redis_client()
    kb_store = KbStore()

    kb_file = kb_store.get_file(file_id)
    if not kb_file:
        raise ValueError(f"FILE_NOT_FOUND: {file_id}")

    kb_id = str(kb_store.get_root_directory_id(kb_file.directory_id))
    kb_store.update_file_index_status(file_id, "indexing", task_id=task_id)
    _publish_step(redis_client, task_id, "task", "running", log=f"开始索引文件 {kb_file.original_name} (kb={kb_id})")

    model_client = ModelClient(settings)
    settings_service = SettingsService()
    runtime_embedding_model = settings_service.get_runtime_value("embedding_model")
    runtime_embedding_dim = settings_service.get_runtime_value("embedding_dim")
    try:
        file_path = Path(settings.kb_storage_path) / kb_file.relative_path
        if not file_path.exists():
            raise FileNotFoundError(f"文件不存在: {file_path}")

        data_dir = Path(settings.kb_storage_path).parent
        parser = build_parser(settings, data_dir, model_client=model_client)
        parse_beat = _make_heartbeat(redis_client, task_id, "parse")

        # 1. 解析（大 PDF 页级心跳）
        documents = _run_step(
            redis_client,
            task_id,
            "parse",
            lambda: parser.parse_file(
                file_path,
                on_progress=lambda done, total: parse_beat(
                    f"解析 PDF：{done}/{total} 页", done, total
                ),
            ),
            log_on_complete=lambda docs: f"解析完成：{len(docs)} 个文档",
        )
        if not documents:
            raise ValueError("未解析到有效内容")

        # 2. 切分
        chunking_stage = ChunkingStage()
        chunking_output = _run_step(
            redis_client,
            task_id,
            "chunking",
            lambda: chunking_stage.execute(ChunkingInput(documents=documents)),
            log_on_complete=lambda out: f"文本切分完成：{len(out.chunks)} 个 chunk",
        )
        new_chunks = chunking_output.chunks
        new_source_ids = {c.source_id for c in new_chunks}

        # 3. Embedding（按批心跳）
        embedding_stage = EmbeddingStage(model_client, settings=settings)
        embed_beat = _make_heartbeat(redis_client, task_id, "embedding")
        embedding_output = _run_step(
            redis_client,
            task_id,
            "embedding",
            lambda: embedding_stage.execute(
                EmbeddingInput(chunks=new_chunks),
                model_name=runtime_embedding_model,
                on_progress=lambda done, total: embed_beat(
                    f"Embedding 进度：{done}/{total}", done, total
                ),
            ),
            log_on_complete=lambda out: f"Embedding 生成完成：{len(out.embeddings)} 条向量",
        )
        new_embeddings = embedding_output.embeddings

        # 4. 合并现有索引 + 新文件（copy-on-write），并原子切换
        metadata_store = IndexMetadataStore()
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        collection_name = f"{settings.milvus_collection}_kb_{kb_id}_{timestamp}_{uuid.uuid4().hex[:8]}"
        bm25_path = Path(settings.bm25_index_path).parent / f"bm25_kb_{kb_id}_{timestamp}_{uuid.uuid4().hex[:8]}.pkl"

        lock = redis_client.lock(
            f"index:active_switch_lock:{kb_id}",
            timeout=3600,
            blocking_timeout=300,
        )
        try:
            with lock:
                active = metadata_store.get_active(kb_id)
                existing: list[tuple[Chunk, list[float]]] = []
                if active:
                    milvus_store = MilvusStore(settings.milvus_uri, active.collection_name)
                    existing = _run_step(
                        redis_client,
                        task_id,
                        "load_active",
                        milvus_store.get_all_chunks,
                        log_on_complete=lambda items: f"加载现有索引：{len(items)} 条 chunk",
                    )
                    # 维度一致性校验：活跃索引与当前 Embedding 模型输出维度不一致时无法直接合并
                    if existing and new_embeddings:
                        active_dim = len(existing[0][1])
                        expected_dim = len(new_embeddings[0].embedding)
                        if active_dim != expected_dim:
                            raise ValueError(
                                f"活跃索引维度 ({active_dim}) 与当前 Embedding 模型输出维度 ({expected_dim}) 不一致，"
                                f"请先执行一次全量重建索引"
                            )

                # 去重：替换同 source_id 的旧 chunk
                filtered_existing = [
                    (chunk, emb) for chunk, emb in existing if chunk.source_id not in new_source_ids
                ]
                combined_chunks = [c for c, _ in filtered_existing] + new_chunks
                combined_embeddings = [e for _, e in filtered_existing] + [
                    e.embedding for e in new_embeddings
                ]

                milvus_store = MilvusStore(settings.milvus_uri, collection_name, dim=runtime_embedding_dim)

                def _write_milvus():
                    milvus_store.create_collection()
                    milvus_store.insert_chunks(combined_chunks, combined_embeddings)
                    return milvus_store

                _run_step(
                    redis_client,
                    task_id,
                    "write_milvus",
                    _write_milvus,
                    log_on_complete=lambda store: f"写入 Milvus 完成：{len(combined_chunks)} 条向量写入 {store.collection_name}",
                )

                bm25_store = BM25Store(bm25_path)

                def _build_bm25():
                    bm25_store.build_index(combined_chunks)
                    bm25_store.save()
                    return bm25_store

                _run_step(
                    redis_client,
                    task_id,
                    "build_bm25",
                    _build_bm25,
                    log_on_complete=lambda store: f"BM25 索引构建完成：{store.index_path}",
                )

                def _atomic_switch():
                    metadata_store.switch_active(
                        collection_name=collection_name,
                        bm25_index_path=str(bm25_path),
                        kb_id=kb_id,
                        reason="file_add",
                        source_changes_json=json.dumps(sorted(new_source_ids)),
                    )

                _run_step(
                    redis_client,
                    task_id,
                    "atomic_switch",
                    _atomic_switch,
                    log_on_complete=lambda _: "索引原子切换完成，新索引已生效",
                )
        except redis.exceptions.LockError as exc:
            _publish_step(redis_client, task_id, "atomic_switch", "failed", log=f"获取索引锁超时: {exc}")
            raise

        # 若该目录启用了 GraphRAG，按新文档触发图索引增量更新
        try:
            from app.stores.graph_schema_store import GraphSchemaStore

            schema_store = GraphSchemaStore()
            schema = schema_store.get_by_directory_id(kb_file.directory_id)
            if schema and schema.enabled:
                from app.tasks.graph_indexing import index_file_graph_task

                graph_task_ids: list[str] = []
                for doc_id in new_source_ids:
                    graph_task = index_file_graph_task.delay(
                        kb_id=str(kb_file.directory_id),
                        doc_id=doc_id,
                    )
                    graph_task_ids.append(graph_task.id)
                _publish_step(
                    redis_client,
                    task_id,
                    "graph_subtask_triggered",
                    "completed",
                    log=f"已触发 {len(graph_task_ids)} 个图索引增量子任务: {', '.join(graph_task_ids)}",
                )
        except Exception as exc:
            logger.warning(
                "index_file_graph_subtask_failed",
                file_id=file_id,
                directory_id=kb_file.directory_id,
                error=str(exc),
            )

        _publish_step(
            redis_client,
            task_id,
            "task",
            "completed",
            log=f"文件索引完成：{kb_file.original_name}",
        )
        kb_store.update_file_index_status(file_id, "indexed", task_id=task_id)
        INDEX_TASK_TOTAL.labels(task_type="file", kb_id=kb_id, status="completed").inc()
        return {
            "collection_name": collection_name,
            "bm25_index_path": str(bm25_path),
            "file_id": file_id,
            "kb_id": kb_id,
        }
    except Exception as exc:
        error_msg = str(exc)
        _publish_step(
            redis_client,
            task_id,
            "task",
            "failed",
            log=error_msg,
        )
        kb_store.update_file_index_status(file_id, "failed", task_id=task_id, index_error=error_msg)
        INDEX_TASK_TOTAL.labels(task_type="file", kb_id=kb_id, status="failed").inc()
        raise
    finally:
        model_client.close()
