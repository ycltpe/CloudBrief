
import structlog
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile

from app.clients.model_client import ModelClient
from app.config import get_settings
from app.dependencies import require_role
from app.models.schemas import (
    GraphShadowReportListResponse,
    GraphShadowReportOut,
    KbAccessListResponse,
    KbAccessRequestOut,
    KbAccessReviewIn,
    KbDirectoryCreate,
    KbDirectoryDeleteResponse,
    KbDirectoryOut,
    KbFileIndexResponse,
    KbFileListResponse,
    KbFileUploadResponse,
    KbGraphSchemaOut,
    KbGraphSchemaRecommendResponse,
    KbGraphSchemaUpdate,
    KbRebuildGraphResponse,
    KbRebuildResponse,
    KbTreeResponse,
    UserOut,
)
from app.services.graph_extraction import GraphExtractionService
from app.services.kb_service import KbService
from app.services.settings_service import SettingsService
from app.stores.db import KbUserAccess
from app.stores.graph_schema_store import GraphSchemaStore
from app.stores.index_metadata import IndexMetadataStore
from app.stores.kb_access import KbAccessStore
from app.stores.milvus import MilvusStore
from app.stores.user import UserStore

logger = structlog.get_logger()
router = APIRouter(prefix="/kb", tags=["admin-kb"])


def get_kb_service() -> KbService:
    return KbService()


def _to_directory_out(directory) -> KbDirectoryOut:
    # service 已经返回 schema 对象，这里保持兼容
    return directory


@router.get("/tree", response_model=KbTreeResponse)
async def list_kb_tree(
    service: KbService = Depends(get_kb_service),
    _current_user: UserOut = Depends(require_role("admin")),
):
    tree = service.build_tree()
    logger.info("admin_list_kb_tree", roots=len(tree))
    return KbTreeResponse(directories=tree)


@router.post("/directories", response_model=KbDirectoryOut)
async def create_kb_directory(
    request: KbDirectoryCreate,
    service: KbService = Depends(get_kb_service),
    current_user: UserOut = Depends(require_role("admin")),
):
    try:
        directory = service.create_directory(
            name=request.name,
            parent_id=request.parent_id,
            description=request.description,
            created_by=current_user.id,
            graphrag_enabled=request.graphrag_enabled,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    logger.info(
        "admin_create_kb_directory",
        directory_id=directory.id,
        parent_id=request.parent_id,
        operator_id=current_user.id,
        graphrag_enabled=request.graphrag_enabled,
    )
    return KbDirectoryOut(
        id=directory.id,
        name=directory.name,
        description=directory.description,
        parent_id=directory.parent_id,
        created_at=directory.created_at.isoformat() if directory.created_at else None,
        updated_at=directory.updated_at.isoformat() if directory.updated_at else None,
        file_count=0,
        graphrag_enabled=request.graphrag_enabled,
        children=[],
    )


@router.delete("/directories/{directory_id}", response_model=KbDirectoryDeleteResponse)
async def delete_kb_directory(
    directory_id: int,
    service: KbService = Depends(get_kb_service),
    current_user: UserOut = Depends(require_role("admin")),
):
    try:
        deleted_files, deleted_dirs = service.delete_directory(directory_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    logger.info(
        "admin_delete_kb_directory",
        directory_id=directory_id,
        deleted_files=deleted_files,
        deleted_directories=deleted_dirs,
        operator_id=current_user.id,
    )
    return KbDirectoryDeleteResponse(
        message="目录已删除",
        deleted_files=deleted_files,
        deleted_directories=deleted_dirs,
    )


@router.get("/directories/{directory_id}/files", response_model=KbFileListResponse)
async def list_kb_files(
    directory_id: int,
    service: KbService = Depends(get_kb_service),
    _current_user: UserOut = Depends(require_role("admin")),
):
    try:
        files = service.list_files(directory_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return KbFileListResponse(files=files)


@router.post("/files", response_model=KbFileUploadResponse)
async def upload_kb_file(
    directory_id: int = Form(...),
    file: UploadFile = File(...),
    service: KbService = Depends(get_kb_service),
    current_user: UserOut = Depends(require_role("admin")),
):
    try:
        result = service.upload_file(
            directory_id=directory_id,
            upload_file=file,
            created_by=current_user.id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    logger.info(
        "admin_upload_kb_file",
        file_id=result.file.id,
        directory_id=directory_id,
        operator_id=current_user.id,
        task_id=result.task_id,
    )
    return result


@router.delete("/files/{file_id}", response_model=dict)
async def delete_kb_file(
    file_id: int,
    service: KbService = Depends(get_kb_service),
    current_user: UserOut = Depends(require_role("admin")),
):
    try:
        service.delete_file(file_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    logger.info("admin_delete_kb_file", file_id=file_id, operator_id=current_user.id)
    return {"message": "文件已删除"}


@router.post("/files/{file_id}/index", response_model=KbFileIndexResponse)
async def index_kb_file(
    file_id: int,
    service: KbService = Depends(get_kb_service),
    current_user: UserOut = Depends(require_role("admin")),
):
    try:
        result = service.trigger_file_index(file_id)
    except ValueError as exc:
        detail = str(exc)
        if "ALREADY_INDEXING" in detail:
            raise HTTPException(status_code=409, detail=detail)
        raise HTTPException(status_code=400, detail=detail)
    except Exception as exc:
        logger.error("admin_kb_file_index_failed", file_id=file_id, error=str(exc), operator_id=current_user.id)
        raise HTTPException(status_code=500, detail=str(exc))

    logger.info("admin_kb_file_index", file_id=file_id, task_id=result.task_id, operator_id=current_user.id)
    return result


@router.post("/rebuild", response_model=KbRebuildResponse)
async def rebuild_kb_index(
    directory_id: int | None = Form(None),
    service: KbService = Depends(get_kb_service),
    current_user: UserOut = Depends(require_role("admin")),
):
    try:
        kb_id = str(directory_id) if directory_id else "default"
        task_id = service.trigger_rebuild(kb_id=kb_id)
    except Exception as exc:
        logger.error("admin_kb_rebuild_failed", error=str(exc), operator_id=current_user.id)
        raise HTTPException(status_code=500, detail=str(exc))

    logger.info("admin_kb_rebuild", task_id=task_id, kb_id=kb_id, operator_id=current_user.id)
    return KbRebuildResponse(task_id=task_id)


def _schema_out(row) -> KbGraphSchemaOut:
    return KbGraphSchemaOut(
        directory_id=int(row.kb_id),
        enabled=row.enabled,
        enabled_by_user=row.enabled_by_user,
        shadow_mode=row.shadow_mode,
        entity_types=[{"name": et.name, "description": et.description, "examples": et.examples} for et in row.entity_types],
        relation_types=[{"name": rt.name, "description": rt.description, "source_types": rt.source_types, "target_types": rt.target_types} for rt in row.relation_types],
        version=row.version,
        updated_at=row.updated_at.isoformat() if row.updated_at else None,
    )


@router.get("/directories/{directory_id}/graph-schema", response_model=KbGraphSchemaOut)
async def get_kb_graph_schema(
    directory_id: int,
    _current_user: UserOut = Depends(require_role("admin")),
):
    store = GraphSchemaStore()
    schema = store.get_by_directory_id(directory_id)
    if not schema:
        schema = store.create_default(directory_id)
    return _schema_out(schema)


@router.put("/directories/{directory_id}/graph-schema", response_model=KbGraphSchemaOut)
async def update_kb_graph_schema(
    directory_id: int,
    request: KbGraphSchemaUpdate,
    _current_user: UserOut = Depends(require_role("admin")),
):
    store = GraphSchemaStore()
    existing = store.get_by_directory_id(directory_id)
    if not existing:
        existing = store.create_default(directory_id)

    from app.models.graph_schemas import EntityType, RelationType
    entity_types = None
    relation_types = None
    if request.entity_types is not None:
        entity_types = [EntityType(**et.model_dump()) for et in request.entity_types]
    if request.relation_types is not None:
        relation_types = [RelationType(**rt.model_dump()) for rt in request.relation_types]

    updated = store.update_schema(
        directory_id,
        enabled=request.enabled,
        enabled_by_user=request.enabled_by_user,
        shadow_mode=request.shadow_mode,
        entity_types=entity_types,
        relation_types=relation_types,
    )
    return _schema_out(updated)


@router.post("/directories/{directory_id}/graph-schema/recommend", response_model=KbGraphSchemaRecommendResponse)
async def recommend_kb_graph_schema(
    directory_id: int,
    request: Request,
    _current_user: UserOut = Depends(require_role("admin")),
):
    settings = get_settings()
    schema_store = GraphSchemaStore()
    existing = schema_store.get_by_directory_id(directory_id)
    if not existing:
        existing = schema_store.create_default(directory_id)

    active = IndexMetadataStore().get_active(kb_id=str(directory_id))
    if not active:
        raise HTTPException(status_code=400, detail="NO_ACTIVE_INDEX")

    milvus_store = MilvusStore(SettingsService().get_runtime_value("milvus_uri"), active.collection_name)
    all_chunks = [chunk for chunk, _ in milvus_store.get_all_chunks()]
    kb_chunks = [c for c in all_chunks if c.source_id.startswith(f"kb/dir_{directory_id}/")]
    if not kb_chunks:
        raise HTTPException(status_code=400, detail="该目录下没有已索引的 chunk，请先重建向量索引")

    model_client = ModelClient(settings)
    try:
        service = GraphExtractionService(model_client)
        recommended = await service.recommend_schema(kb_chunks[:10], kb_id=str(directory_id))
    except Exception as exc:
        logger.error("admin_kb_graph_schema_recommend_failed", directory_id=directory_id, error=str(exc))
        raise HTTPException(status_code=502, detail="模型服务暂不可用，schema 推荐失败，请稍后重试")
    finally:
        await model_client.aclose()

    return KbGraphSchemaRecommendResponse(
        directory_id=directory_id,
        entity_types=[{"name": et.name, "description": et.description, "examples": et.examples} for et in recommended.entity_types],
        relation_types=[{"name": rt.name, "description": rt.description, "source_types": rt.source_types, "target_types": rt.target_types} for rt in recommended.relation_types],
    )


@router.post("/directories/{directory_id}/graph-schema/rebuild", response_model=KbRebuildGraphResponse)
async def rebuild_kb_graph(
    directory_id: int,
    service: KbService = Depends(get_kb_service),
    _current_user: UserOut = Depends(require_role("admin")),
):
    try:
        result = service.trigger_graph_rebuild(directory_id)
    except Exception as exc:
        logger.error("admin_kb_graph_rebuild_failed", directory_id=directory_id, error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc))
    return result


@router.get("/graph-shadow-reports", response_model=GraphShadowReportListResponse)
async def list_graph_shadow_reports(
    kb_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
    _current_user: UserOut = Depends(require_role("admin")),
):
    from app.stores.graph_shadow_store import GraphShadowStore

    store = GraphShadowStore()
    records, total = store.list_records(kb_id=kb_id, limit=limit, offset=offset)
    summary = store.summary(kb_id=kb_id)

    def _to_out(record):
        import json
        try:
            metrics = json.loads(record.diff_metrics_json or "{}")
        except Exception:
            metrics = {}
        return GraphShadowReportOut(
            id=record.id,
            kb_id=record.kb_id,
            user_id=record.user_id,
            question=record.question,
            vector_answer=record.vector_answer,
            graph_answer=record.graph_answer,
            diff_ratio=metrics.get("diff_ratio"),
            created_at=record.created_at.isoformat() if record.created_at else None,
        )

    return GraphShadowReportListResponse(
        total=total,
        items=[_to_out(r) for r in records],
        avg_diff_ratio=summary.get("avg_diff_ratio"),
    )


# 知识库访问权限审批（admin）
def _access_out(access, username: str | None = None) -> KbAccessRequestOut:
    return KbAccessRequestOut(
        id=access.id,
        kb_id=access.kb_id,
        user_id=access.user_id,
        username=username,
        status=access.status,
        created_by=access.created_by,
        created_at=access.created_at.isoformat() if access.created_at else None,
        updated_at=access.updated_at.isoformat() if access.updated_at else None,
    )


@router.get("/access-requests", response_model=KbAccessListResponse)
async def list_kb_access_requests(
    status: str | None = None,
    kb_id: str | None = None,
    offset: int = 0,
    limit: int = 100,
    _current_user: UserOut = Depends(require_role("admin")),
):
    store = KbAccessStore()
    user_store = UserStore()
    if kb_id:
        items, total = store.list_access_by_kb(kb_id=kb_id, status=status, offset=offset, limit=limit)
    elif status:
        # 按状态查询所有知识库
        with store._session_factory() as session:
            query = session.query(KbUserAccess)
            query = query.filter_by(status=status)
            total = query.count()
            items = query.order_by(KbUserAccess.created_at.desc()).offset(offset).limit(limit).all()
    else:
        items, total = store.list_pending_requests(offset=offset, limit=limit)
    users, _ = user_store.list_all(limit=10000)
    user_map = {u.id: u.username for u in users}
    return KbAccessListResponse(
        total=total,
        items=[_access_out(a, user_map.get(a.user_id)) for a in items],
    )


@router.post("/access-requests/{access_id}/review", response_model=KbAccessRequestOut)
async def review_kb_access_request(
    access_id: int,
    request: KbAccessReviewIn,
    current_user: UserOut = Depends(require_role("admin")),
):
    store = KbAccessStore()
    access = store.update_request(access_id, request.status, reviewed_by=current_user.id)
    if not access:
        raise HTTPException(status_code=404, detail="ACCESS_REQUEST_NOT_FOUND")
    user = UserStore().get_by_id(access.user_id)
    logger.info(
        "admin_review_kb_access",
        access_id=access_id,
        kb_id=access.kb_id,
        user_id=access.user_id,
        status=request.status,
        operator_id=current_user.id,
    )
    return _access_out(access, user.username if user else None)
