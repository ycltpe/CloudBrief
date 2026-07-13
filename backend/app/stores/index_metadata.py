
from app.stores.db import IndexMetadata, get_session_factory


class IndexMetadataStore:
    """负责 active index 元数据的原子切换（按知识库隔离）。"""

    def __init__(self, session_factory=None):
        self._session_factory = session_factory or get_session_factory()

    def get_active(self, kb_id: str = "default") -> IndexMetadata | None:
        with self._session_factory() as session:
            return session.query(IndexMetadata).filter_by(kb_id=kb_id, is_active=True).first()

    def get_by_version(self, kb_id: str, version: int) -> IndexMetadata | None:
        with self._session_factory() as session:
            return session.query(IndexMetadata).filter_by(kb_id=kb_id, version=version).first()

    def list_history(self, kb_id: str = "default", limit: int = 20) -> list[IndexMetadata]:
        with self._session_factory() as session:
            return (
                session.query(IndexMetadata)
                .filter_by(kb_id=kb_id)
                .order_by(IndexMetadata.version.desc())
                .limit(limit)
                .all()
            )

    def get_next_version(self, kb_id: str = "default") -> int:
        with self._session_factory() as session:
            max_version = (
                session.query(IndexMetadata.version)
                .filter_by(kb_id=kb_id)
                .order_by(IndexMetadata.version.desc())
                .first()
            )
            return (max_version[0] if max_version else 0) + 1

    def switch_active(
        self,
        collection_name: str,
        bm25_index_path: str,
        kb_id: str = "default",
        reason: str = "rebuild",
        source_changes_json: str = "[]",
    ) -> int:
        """原子切换：把新记录置为 active，旧记录置为 inactive，返回新记录 id。"""
        with self._session_factory() as session:
            current = session.query(IndexMetadata).filter_by(kb_id=kb_id, is_active=True).first()
            session.query(IndexMetadata).filter_by(kb_id=kb_id, is_active=True).update(
                {"is_active": False},
                synchronize_session=False,
            )
            new_version = self.get_next_version(kb_id)
            new_meta = IndexMetadata(
                kb_id=kb_id,
                collection_name=collection_name,
                bm25_index_path=bm25_index_path,
                is_active=True,
                version=new_version,
                parent_id=current.id if current else None,
                reason=reason,
                source_changes_json=source_changes_json,
            )
            session.add(new_meta)
            session.commit()
            return new_meta.id
