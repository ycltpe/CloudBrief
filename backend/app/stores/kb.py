from datetime import datetime

from sqlalchemy import func
from sqlalchemy.orm import joinedload

from app.stores.db import KbDirectory, KbFile, get_session_factory


class KbStore:
    """知识库目录与文件持久化仓库。"""

    def __init__(self, session_factory=None):
        self._session_factory = session_factory or get_session_factory()

    def create_directory(
        self,
        name: str,
        parent_id: int | None = None,
        description: str | None = None,
        created_by: int | None = None,
    ) -> KbDirectory:
        with self._session_factory() as session:
            if session.query(KbDirectory).filter_by(parent_id=parent_id, name=name).first():
                raise ValueError("DIRECTORY_NAME_EXISTS")
            directory = KbDirectory(
                parent_id=parent_id,
                name=name,
                description=description,
                created_by=created_by,
            )
            session.add(directory)
            session.commit()
            session.refresh(directory)
            return directory

    def get_directory(self, directory_id: int) -> KbDirectory | None:
        with self._session_factory() as session:
            return (
                session.query(KbDirectory)
                .options(joinedload(KbDirectory.files))
                .filter_by(id=directory_id)
                .first()
            )

    def get_root_directory_id(self, directory_id: int) -> int:
        """递归向上查找顶层目录 id，作为知识库标识 kb_id。"""
        with self._session_factory() as session:
            current_id = directory_id
            while current_id:
                directory = session.query(KbDirectory).filter_by(id=current_id).first()
                if not directory:
                    break
                if directory.parent_id is None:
                    return directory.id
                current_id = directory.parent_id
            return directory_id

    def list_root_directories(self) -> list[KbDirectory]:
        with self._session_factory() as session:
            return (
                session.query(KbDirectory)
                .filter_by(parent_id=None)
                .order_by(KbDirectory.created_at.desc())
                .all()
            )

    def list_children(self, parent_id: int) -> list[KbDirectory]:
        with self._session_factory() as session:
            return (
                session.query(KbDirectory)
                .filter_by(parent_id=parent_id)
                .order_by(KbDirectory.name)
                .all()
            )

    def list_all_directories(self) -> list[KbDirectory]:
        with self._session_factory() as session:
            return session.query(KbDirectory).all()

    def list_all_files(self) -> list[KbFile]:
        with self._session_factory() as session:
            return session.query(KbFile).all()

    def delete_directory(self, directory_id: int) -> bool:
        with self._session_factory() as session:
            directory = session.query(KbDirectory).filter_by(id=directory_id).first()
            if not directory:
                return False
            session.delete(directory)
            session.commit()
            return True

    def create_file(
        self,
        directory_id: int,
        original_name: str,
        stored_name: str,
        relative_path: str,
        size: int,
        mime_type: str | None,
        created_by: int | None = None,
        content_hash: str | None = None,
    ) -> KbFile:
        with self._session_factory() as session:
            file = KbFile(
                directory_id=directory_id,
                original_name=original_name,
                stored_name=stored_name,
                relative_path=relative_path,
                size=size,
                mime_type=mime_type,
                created_by=created_by,
                content_hash=content_hash,
            )
            session.add(file)
            session.commit()
            session.refresh(file)
            return file

    def get_file(self, file_id: int) -> KbFile | None:
        with self._session_factory() as session:
            return session.query(KbFile).filter_by(id=file_id).first()

    def list_files(self, directory_id: int) -> list[KbFile]:
        with self._session_factory() as session:
            return (
                session.query(KbFile)
                .filter_by(directory_id=directory_id)
                .order_by(KbFile.created_at.desc())
                .all()
            )

    def delete_file(self, file_id: int) -> bool:
        with self._session_factory() as session:
            file = session.query(KbFile).filter_by(id=file_id).first()
            if not file:
                return False
            session.delete(file)
            session.commit()
            return True

    def update_file_index_status(
        self,
        file_id: int,
        status: str,
        task_id: str | None = None,
        index_error: str | None = None,
        content_hash: str | None = None,
    ) -> KbFile | None:
        with self._session_factory() as session:
            file = session.query(KbFile).filter_by(id=file_id).first()
            if not file:
                return None
            file.status = status
            if task_id is not None:
                file.last_task_id = task_id
            if index_error is not None:
                file.index_error = index_error
            if content_hash is not None:
                file.content_hash = content_hash
            if status == "indexed":
                file.last_indexed_at = datetime.utcnow()
            session.commit()
            session.refresh(file)
            return file

    def count_files(self, directory_id: int) -> int:
        with self._session_factory() as session:
            return (
                session.query(func.count(KbFile.id)).filter_by(directory_id=directory_id).scalar() or 0
            )
