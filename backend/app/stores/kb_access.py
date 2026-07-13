from datetime import datetime

from sqlalchemy import func

from app.stores.db import KbUserAccess, User, get_session_factory


class KbAccessStore:
    """知识库访问权限持久化仓库。"""

    def __init__(self, session_factory=None):
        self._session_factory = session_factory or get_session_factory()

    def grant_access(
        self,
        kb_id: str,
        user_id: int,
        created_by: int | None = None,
        status: str = "approved",
    ) -> KbUserAccess:
        """直接授权（admin 使用）或创建访问记录。"""
        with self._session_factory() as session:
            existing = (
                session.query(KbUserAccess)
                .filter_by(kb_id=kb_id, user_id=user_id)
                .first()
            )
            if existing:
                existing.status = status
                existing.created_by = created_by
                existing.updated_at = datetime.utcnow()
                session.commit()
                session.refresh(existing)
                return existing

            access = KbUserAccess(
                kb_id=kb_id,
                user_id=user_id,
                status=status,
                created_by=created_by,
            )
            session.add(access)
            session.commit()
            session.refresh(access)
            return access

    def request_access(self, kb_id: str, user_id: int) -> KbUserAccess:
        """用户提交访问申请，状态为 pending。"""
        with self._session_factory() as session:
            existing = (
                session.query(KbUserAccess)
                .filter_by(kb_id=kb_id, user_id=user_id)
                .first()
            )
            if existing:
                if existing.status == "approved":
                    return existing
                existing.status = "pending"
                existing.updated_at = datetime.utcnow()
                session.commit()
                session.refresh(existing)
                return existing

            access = KbUserAccess(kb_id=kb_id, user_id=user_id, status="pending")
            session.add(access)
            session.commit()
            session.refresh(access)
            return access

    def update_request(
        self,
        access_id: int,
        status: str,
        reviewed_by: int | None = None,
    ) -> KbUserAccess | None:
        """admin 审批或拒绝访问申请。"""
        with self._session_factory() as session:
            access = session.query(KbUserAccess).filter_by(id=access_id).first()
            if not access:
                return None
            access.status = status
            access.created_by = reviewed_by
            access.updated_at = datetime.utcnow()
            session.commit()
            session.refresh(access)
            return access

    def list_access_by_kb(
        self,
        kb_id: str,
        status: str | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[list[KbUserAccess], int]:
        with self._session_factory() as session:
            query = session.query(KbUserAccess).filter_by(kb_id=kb_id)
            if status:
                query = query.filter_by(status=status)
            total = session.query(func.count(KbUserAccess.id)).filter_by(kb_id=kb_id)
            if status:
                total = total.filter_by(status=status)
            rows = (
                query.order_by(KbUserAccess.created_at.desc())
                .offset(offset)
                .limit(limit)
                .all()
            )
            return rows, total.scalar() or 0

    def list_access_by_user(
        self,
        user_id: int,
        status: str | None = None,
    ) -> list[KbUserAccess]:
        with self._session_factory() as session:
            query = session.query(KbUserAccess).filter_by(user_id=user_id)
            if status:
                query = query.filter_by(status=status)
            return query.order_by(KbUserAccess.created_at.desc()).all()

    def list_pending_requests(
        self,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[list[KbUserAccess], int]:
        with self._session_factory() as session:
            query = session.query(KbUserAccess).filter_by(status="pending")
            total = (
                session.query(func.count(KbUserAccess.id))
                .filter_by(status="pending")
                .scalar()
                or 0
            )
            rows = (
                query.order_by(KbUserAccess.created_at.desc())
                .offset(offset)
                .limit(limit)
                .all()
            )
            return rows, total

    def get_user_accessible_kb_ids(self, user_id: int, include_default: bool = True) -> list[str]:
        """返回用户有权限访问的知识库 id 列表。"""
        with self._session_factory() as session:
            query = (
                session.query(KbUserAccess.kb_id)
                .filter_by(user_id=user_id, status="approved")
                .distinct()
            )
            kb_ids = [row[0] for row in query.all()]
            if include_default and "default" not in kb_ids:
                kb_ids.insert(0, "default")
            return kb_ids

    def check_access(self, kb_id: str, user_id: int) -> bool:
        """检查用户是否有权限访问指定知识库。"""
        if kb_id == "default":
            return True
        with self._session_factory() as session:
            return (
                session.query(KbUserAccess)
                .filter_by(kb_id=kb_id, user_id=user_id, status="approved")
                .first()
                is not None
            )

    def revoke_access(self, kb_id: str, user_id: int) -> bool:
        with self._session_factory() as session:
            access = (
                session.query(KbUserAccess)
                .filter_by(kb_id=kb_id, user_id=user_id)
                .first()
            )
            if not access:
                return False
            session.delete(access)
            session.commit()
            return True

    def get_access_record(
        self,
        kb_id: str,
        user_id: int,
    ) -> KbUserAccess | None:
        with self._session_factory() as session:
            return (
                session.query(KbUserAccess)
                .filter_by(kb_id=kb_id, user_id=user_id)
                .first()
            )

    def get_access_by_id(self, access_id: int) -> KbUserAccess | None:
        with self._session_factory() as session:
            return session.query(KbUserAccess).filter_by(id=access_id).first()

    def list_users_with_access(self, kb_id: str) -> list[User]:
        """返回对某知识库有访问权限的用户列表（用于管理后台）。"""
        with self._session_factory() as session:
            return (
                session.query(User)
                .join(KbUserAccess, User.id == KbUserAccess.user_id)
                .filter(KbUserAccess.kb_id == kb_id, KbUserAccess.status == "approved")
                .all()
            )
