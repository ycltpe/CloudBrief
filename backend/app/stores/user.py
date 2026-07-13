
from sqlalchemy import func

from app.stores.db import User, get_session_factory


class UserStore:
    """用户账号持久化仓库。"""

    def __init__(self, session_factory=None):
        self._session_factory = session_factory or get_session_factory()

    def create(self, username: str, password_hash: str, role: str = "user") -> User:
        with self._session_factory() as session:
            user = User(username=username, password_hash=password_hash, role=role)
            session.add(user)
            session.commit()
            session.refresh(user)
            return user

    def get_by_username(self, username: str) -> User | None:
        with self._session_factory() as session:
            return session.query(User).filter_by(username=username).first()

    def get_by_id(self, user_id: int) -> User | None:
        with self._session_factory() as session:
            return session.query(User).filter_by(id=user_id).first()

    def list_all(
        self,
        limit: int = 20,
        offset: int = 0,
        q: str | None = None,
        role: str | None = None,
    ) -> tuple[list[User], int]:
        with self._session_factory() as session:
            query = session.query(User)
            if q:
                query = query.filter(User.username.ilike(f"%{q}%"))
            if role:
                query = query.filter(User.role == role)
            total = query.count()
            items = (
                query.order_by(User.created_at.desc())
                .offset(offset)
                .limit(limit)
                .all()
            )
            return items, total

    def count(self) -> int:
        with self._session_factory() as session:
            return session.query(func.count(User.id)).scalar() or 0

    def count_by_role(self, role: str) -> int:
        with self._session_factory() as session:
            return session.query(func.count(User.id)).filter(User.role == role).scalar() or 0

    def delete(self, user_id: int) -> bool:
        with self._session_factory() as session:
            user = session.query(User).filter_by(id=user_id).first()
            if not user:
                return False
            session.delete(user)
            session.commit()
            return True
