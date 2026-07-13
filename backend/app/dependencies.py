from collections.abc import Callable

import structlog
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.models.schemas import UserOut
from app.services.auth_service import AuthService

logger = structlog.get_logger()
security = HTTPBearer(auto_error=False)


def _extract_token(request: Request, credentials: HTTPAuthorizationCredentials | None) -> str | None:
    if credentials:
        return credentials.credentials
    # 允许从 Cookie 读取 token，便于 SSR/中间件场景
    token = request.cookies.get("access_token")
    if token:
        return token
    # SSE 等无法自定义 Header 的场景，允许通过 URL query token 鉴权
    return request.query_params.get("token")


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> UserOut:
    token = _extract_token(request, credentials)
    if not token:
        raise HTTPException(status_code=401, detail="Missing authentication token")

    auth_service = AuthService()
    user = auth_service.get_user_by_token(token)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    return _user_out(user)


async def get_current_user_optional(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> UserOut | None:
    """可选认证：有合法 token 时返回用户，否则返回 None，供同时服务匿名与登录场景的接口使用。"""
    token = _extract_token(request, credentials)
    if not token:
        return None
    try:
        auth_service = AuthService()
        user = auth_service.get_user_by_token(token)
        if not user:
            return None
        return _user_out(user)
    except Exception:
        return None


def _user_out(user) -> UserOut:
    return UserOut(
        id=user.id,
        username=user.username,
        role=user.role,
        created_at=user.created_at.isoformat() if user.created_at else None,
    )


def require_role(*allowed_roles: str) -> Callable:
    def checker(current_user: UserOut = Depends(get_current_user)) -> UserOut:
        if current_user.role not in allowed_roles:
            logger.warning(
                "forbidden_access",
                user_id=current_user.id,
                role=current_user.role,
                required_roles=list(allowed_roles),
            )
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return current_user

    return checker
