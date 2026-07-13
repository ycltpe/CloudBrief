from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.security import HTTPBearer

from app.dependencies import get_current_user
from app.models.schemas import LoginRequest, LoginResponse, UserCreate, UserOut
from app.services.auth_service import AuthService

router = APIRouter(tags=["auth"])
auth_service = AuthService()
security = HTTPBearer(auto_error=False)


@router.post("/auth/register", response_model=UserOut)
async def register(request: UserCreate):
    try:
        user = auth_service.register(
            username=request.username,
            password=request.password,
            role=request.role,
        )
        return UserOut(
            id=user.id,
            username=user.username,
            role=user.role,
            created_at=user.created_at.isoformat() if user.created_at else None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.post("/auth/login", response_model=LoginResponse)
async def login(response: Response, request: LoginRequest):
    try:
        user, access_token = auth_service.login(
            username=request.username,
            password=request.password,
        )
    except ValueError:
        raise HTTPException(status_code=401, detail="INVALID_CREDENTIALS")

    # 同时写入 Cookie，方便前端 SSR / middleware 场景
    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        secure=False,  # 本地开发环境
        samesite="lax",
        max_age=60 * 60 * 24,  # 1 day
    )

    return LoginResponse(
        access_token=access_token,
        user=UserOut(
            id=user.id,
            username=user.username,
            role=user.role,
            created_at=user.created_at.isoformat() if user.created_at else None,
        ),
    )


@router.post("/auth/logout")
async def logout(response: Response):
    response.delete_cookie(key="access_token")
    return {"message": "已退出登录"}


@router.get("/auth/me", response_model=UserOut)
async def me(current_user: UserOut = Depends(get_current_user)):
    return current_user
