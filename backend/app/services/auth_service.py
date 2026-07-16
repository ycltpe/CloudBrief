from datetime import datetime, timedelta

import bcrypt
import structlog
from jose import JWTError, jwt

from app.models.schemas import TokenPayload
from app.services.settings_service import SettingsService
from app.stores.db import User
from app.stores.user import UserStore

logger = structlog.get_logger()

_settings_service = SettingsService()


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(
        plain_password.encode("utf-8"),
        hashed_password.encode("utf-8"),
    )


def get_password_hash(password: str) -> str:
    # bcrypt 输入上限为 72 字节；超过时截断并记录警告
    password_bytes = password.encode("utf-8")
    if len(password_bytes) > 72:
        logger.warning("password_truncated_to_72_bytes")
        password_bytes = password_bytes[:72]
    hashed = bcrypt.hashpw(password_bytes, bcrypt.gensalt())
    return hashed.decode("utf-8")


def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(
            minutes=_settings_service.get_runtime_value("jwt_access_token_expire_minutes")
        )
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(
        to_encode,
        _settings_service.get_runtime_value("jwt_secret_key"),
        algorithm=_settings_service.get_runtime_value("jwt_algorithm"),
    )
    return encoded_jwt


def decode_access_token(token: str) -> TokenPayload | None:
    try:
        payload = jwt.decode(
            token,
            _settings_service.get_runtime_value("jwt_secret_key"),
            algorithms=[_settings_service.get_runtime_value("jwt_algorithm")],
        )
        user_id = payload.get("sub")
        if user_id is None:
            return None
        return TokenPayload(user_id=int(user_id), exp=payload.get("exp"))
    except (JWTError, ValueError):
        return None


class AuthService:
    """认证服务：注册、登录、密码校验、JWT 签发。"""

    def __init__(self, user_store: UserStore | None = None):
        self.user_store = user_store or UserStore()

    def register(self, username: str, password: str, role: str = "user") -> User:
        if self.user_store.get_by_username(username):
            raise ValueError("USERNAME_EXISTS")
        hashed = get_password_hash(password)
        user = self.user_store.create(username=username, password_hash=hashed, role=role)
        logger.info("user_registered", user_id=user.id, username=username, role=role)
        return user

    def authenticate(self, username: str, password: str) -> User | None:
        user = self.user_store.get_by_username(username)
        if not user:
            return None
        if not verify_password(password, user.password_hash):
            return None
        return user

    def login(self, username: str, password: str) -> tuple[User, str]:
        user = self.authenticate(username, password)
        if not user:
            raise ValueError("INVALID_CREDENTIALS")
        access_token = create_access_token(data={"sub": str(user.id)})
        logger.info("user_login", user_id=user.id, username=username)
        return user, access_token

    def get_user_by_token(self, token: str) -> User | None:
        payload = decode_access_token(token)
        if not payload:
            return None
        return self.user_store.get_by_id(payload.user_id)
