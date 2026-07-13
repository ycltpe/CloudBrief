
import structlog
from fastapi import APIRouter, Depends, HTTPException

from app.dependencies import require_role
from app.models.schemas import AdminUserCreate, UserListResponse, UserOut
from app.services.auth_service import AuthService, get_password_hash
from app.stores.user import UserStore

logger = structlog.get_logger()
router = APIRouter(prefix="/users", tags=["admin-users"])
user_store = UserStore()
auth_service = AuthService(user_store)


def _to_out(user) -> UserOut:
    return UserOut(
        id=user.id,
        username=user.username,
        role=user.role,
        created_at=user.created_at.isoformat() if user.created_at else None,
    )


@router.get("", response_model=UserListResponse)
async def list_users(
    q: str | None = None,
    role: str | None = None,
    limit: int = 20,
    offset: int = 0,
    _current_user: UserOut = Depends(require_role("admin")),
):
    if limit < 1 or limit > 100:
        raise HTTPException(status_code=400, detail="limit must be between 1 and 100")
    if offset < 0:
        raise HTTPException(status_code=400, detail="offset must be non-negative")

    items, total = user_store.list_all(limit=limit, offset=offset, q=q, role=role)
    logger.info("admin_list_users", q=q, role=role, limit=limit, offset=offset, total=total)
    return UserListResponse(total=total, items=[_to_out(u) for u in items])


@router.post("", response_model=UserOut)
async def create_user(
    request: AdminUserCreate,
    _current_user: UserOut = Depends(require_role("admin")),
):
    if user_store.get_by_username(request.username):
        raise HTTPException(status_code=409, detail="USERNAME_EXISTS")

    hashed = get_password_hash(request.password)
    user = user_store.create(username=request.username, password_hash=hashed, role=request.role)
    logger.info("admin_create_user", user_id=user.id, username=user.username, role=user.role)
    return _to_out(user)


@router.delete("/{user_id}")
async def delete_user(
    user_id: int,
    _current_user: UserOut = Depends(require_role("admin")),
):
    target = user_store.get_by_id(user_id)
    if not target:
        raise HTTPException(status_code=404, detail="USER_NOT_FOUND")

    # 禁止删除最后一个 admin
    if target.role == "admin" and user_store.count_by_role("admin") <= 1:
        raise HTTPException(status_code=403, detail="CANNOT_DELETE_LAST_ADMIN")

    # 禁止 self-delete（可选的安全策略）
    if _current_user.id == user_id:
        raise HTTPException(status_code=403, detail="CANNOT_DELETE_SELF")

    success = user_store.delete(user_id)
    if not success:
        raise HTTPException(status_code=500, detail="DELETE_FAILED")

    logger.info("admin_delete_user", target_user_id=user_id, operator_id=_current_user.id)
    return {"message": "用户已删除"}
