import structlog
from fastapi import APIRouter, Depends

from app.dependencies import require_role
from app.models.schemas import (
    KbAccessRequestIn,
    KbAccessRequestOut,
    KbInfoOut,
    UserAccessibleKbListResponse,
    UserOut,
)
from app.stores.db import KbDirectory
from app.stores.kb import KbStore
from app.stores.kb_access import KbAccessStore

logger = structlog.get_logger()
router = APIRouter(prefix="/kb-access", tags=["kb-access"])


def _kb_info(directory: KbDirectory) -> KbInfoOut:
    return KbInfoOut(
        kb_id=str(directory.id),
        name=directory.name,
        description=directory.description,
    )


@router.get("/accessible", response_model=UserAccessibleKbListResponse)
async def list_accessible_kbs(
    current_user: UserOut = Depends(require_role("admin", "qa", "user")),
):
    """返回当前用户有权限访问的知识库列表。admin 可访问全部。"""
    kb_store = KbStore()
    if current_user.role == "admin":
        directories = kb_store.list_root_directories()
    else:
        access_store = KbAccessStore()
        kb_ids = access_store.get_user_accessible_kb_ids(current_user.id, include_default=True)
        directories = [kb_store.get_directory(int(kb_id)) for kb_id in kb_ids if kb_id.isdigit()]
        directories = [d for d in directories if d is not None]

    return UserAccessibleKbListResponse(
        items=[_kb_info(d) for d in directories],
    )


@router.post("/request", response_model=KbAccessRequestOut)
async def request_kb_access(
    request: KbAccessRequestIn,
    current_user: UserOut = Depends(require_role("admin", "qa", "user")),
):
    """用户申请访问某个知识库。"""
    access_store = KbAccessStore()
    existing = access_store.get_access_record(request.kb_id, current_user.id)
    if existing and existing.status == "approved":
        return KbAccessRequestOut(
            id=existing.id,
            kb_id=existing.kb_id,
            user_id=existing.user_id,
            status=existing.status,
            created_by=existing.created_by,
            created_at=existing.created_at.isoformat() if existing.created_at else None,
            updated_at=existing.updated_at.isoformat() if existing.updated_at else None,
        )

    access = access_store.request_access(request.kb_id, current_user.id)
    logger.info(
        "kb_access_requested",
        kb_id=request.kb_id,
        user_id=current_user.id,
        access_id=access.id,
    )
    return KbAccessRequestOut(
        id=access.id,
        kb_id=access.kb_id,
        user_id=access.user_id,
        status=access.status,
        created_by=access.created_by,
        created_at=access.created_at.isoformat() if access.created_at else None,
        updated_at=access.updated_at.isoformat() if access.updated_at else None,
    )


@router.get("/my-requests", response_model=list[KbAccessRequestOut])
async def list_my_kb_access_requests(
    current_user: UserOut = Depends(require_role("admin", "qa", "user")),
):
    """返回当前用户提交的所有访问申请。"""
    access_store = KbAccessStore()
    items = access_store.list_access_by_user(current_user.id)
    return [
        KbAccessRequestOut(
            id=a.id,
            kb_id=a.kb_id,
            user_id=a.user_id,
            status=a.status,
            created_by=a.created_by,
            created_at=a.created_at.isoformat() if a.created_at else None,
            updated_at=a.updated_at.isoformat() if a.updated_at else None,
        )
        for a in items
    ]
