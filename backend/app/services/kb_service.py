import hashlib
import shutil
import uuid
from collections import Counter
from datetime import datetime
from pathlib import Path

import structlog
from fastapi import UploadFile

from app.config import get_settings
from app.models.schemas import (
    KbDirectoryOut,
    KbFileIndexResponse,
    KbFileOut,
    KbFileUploadResponse,
    KbRebuildGraphResponse,
)
from app.services.index_service import IndexService
from app.services.settings_service import SettingsService
from app.stores.db import KbDirectory, KbFile
from app.stores.graph_schema_store import GraphSchemaStore
from app.stores.kb import KbStore

logger = structlog.get_logger()

KB_ALLOWED_EXTENSIONS = {".md", ".json", ".csv", ".txt", ".pdf", ".docx", ".xlsx"}
KB_ALLOWED_EXTENSIONS_LABEL = "PDF (.pdf)、Word (.docx)、Excel (.xlsx)、Markdown (.md)、JSON (.json)、CSV (.csv)、TXT (.txt)"
# 老二进制格式：给明确指引而非泛泛的"不支持"
KB_LEGACY_EXTENSIONS = {".doc", ".xls"}


class KbService:
    """知识库目录、文件管理与索引重建编排。"""

    def __init__(
        self,
        store: KbStore | None = None,
        index_service: IndexService | None = None,
        settings_service: SettingsService | None = None,
        graph_schema_store: GraphSchemaStore | None = None,
    ):
        self.store = store or KbStore()
        self.index_service = index_service or IndexService()
        self.settings_service = settings_service or SettingsService()
        self.graph_schema_store = graph_schema_store or GraphSchemaStore()
        self.settings = get_settings()
        self.storage_path = Path(self.settings_service.get_runtime_value("kb_storage_path"))
        self.storage_path.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _validate_directory_name(name: str) -> str:
        cleaned = name.strip()
        if not cleaned:
            raise ValueError("目录名称不能为空")
        if len(cleaned) > 100:
            raise ValueError("目录名称不能超过 100 个字符")
        if cleaned in {".", ".."} or "/" in cleaned or "\\" in cleaned:
            raise ValueError("目录名称不能包含 / 或 \\")
        return cleaned

    def _directory_storage_dir(self, directory_id: int) -> Path:
        return self.storage_path / f"dir_{directory_id}"

    @staticmethod
    def _safe_stored_name(original_name: str) -> str:
        original_path = Path(original_name)
        ext = original_path.suffix.lower()
        stem = original_path.stem[:80]
        safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in stem)
        return f"{safe}_{uuid.uuid4().hex[:8]}{ext}"

    def _unlink_file(self, relative_path: str) -> None:
        file_path = self.storage_path / relative_path
        try:
            if file_path.exists():
                file_path.unlink()
        except OSError as exc:
            logger.warning("kb_delete_file_failed", path=str(file_path), error=str(exc))

    def _rmdir_storage(self, directory_id: int) -> None:
        dir_path = self._directory_storage_dir(directory_id)
        try:
            if dir_path.exists():
                shutil.rmtree(dir_path)
        except OSError as exc:
            logger.warning("kb_delete_directory_failed", path=str(dir_path), error=str(exc))

    def _to_directory_out(
        self,
        directory: KbDirectory,
        children_map: dict[int, list[KbDirectory]],
        file_counts: dict[int, int],
        schema_enabled_map: dict[int, bool],
    ) -> KbDirectoryOut:
        child_outs = [
            self._to_directory_out(c, children_map, file_counts, schema_enabled_map)
            for c in children_map.get(directory.id, [])
        ]
        total_files = file_counts.get(directory.id, 0) + sum(
            c.file_count for c in child_outs
        )
        return KbDirectoryOut(
            id=directory.id,
            name=directory.name,
            description=directory.description,
            parent_id=directory.parent_id,
            created_at=directory.created_at.isoformat() if directory.created_at else None,
            updated_at=directory.updated_at.isoformat() if directory.updated_at else None,
            file_count=total_files,
            graphrag_enabled=schema_enabled_map.get(directory.id, False),
            children=child_outs,
        )

    def build_tree(self) -> list[KbDirectoryOut]:
        all_dirs = self.store.list_all_directories()
        all_files = self.store.list_all_files()
        file_counts = Counter(f.directory_id for f in all_files)

        with self.graph_schema_store._session_factory() as session:
            from app.stores.db import KbGraphSchema
            schema_enabled_map = {
                row.directory_id: row.enabled
                for row in session.query(KbGraphSchema).all()
            }

        children_map: dict[int, list[KbDirectory]] = {}
        root_dirs: list[KbDirectory] = []
        for d in all_dirs:
            if d.parent_id is None:
                root_dirs.append(d)
            else:
                children_map.setdefault(d.parent_id, []).append(d)
        for lst in children_map.values():
            lst.sort(key=lambda x: x.name)
        root_dirs.sort(key=lambda x: x.created_at or datetime.min, reverse=True)

        return [self._to_directory_out(d, children_map, file_counts, schema_enabled_map) for d in root_dirs]

    def create_directory(
        self,
        name: str,
        parent_id: int | None = None,
        description: str | None = None,
        created_by: int | None = None,
        graphrag_enabled: bool = False,
    ) -> KbDirectory:
        cleaned_name = self._validate_directory_name(name)
        if parent_id is not None and not self.store.get_directory(parent_id):
            raise ValueError("PARENT_DIRECTORY_NOT_FOUND")
        directory = self.store.create_directory(
            name=cleaned_name,
            parent_id=parent_id,
            description=description,
            created_by=created_by,
        )
        self.graph_schema_store.create_default(
            directory_id=directory.id,
            enabled_by_user=graphrag_enabled,
        )
        return directory

    def upload_file(
        self,
        directory_id: int,
        upload_file: UploadFile,
        created_by: int | None = None,
    ) -> KbFileUploadResponse:
        directory = self.store.get_directory(directory_id)
        if not directory:
            raise ValueError("DIRECTORY_NOT_FOUND")

        original_name = Path(upload_file.filename or "unnamed").name
        ext = Path(original_name).suffix.lower()
        if ext in KB_LEGACY_EXTENSIONS:
            raise ValueError(f"暂仅支持新版格式（.docx/.xlsx），请将 {ext} 文件另存后上传")
        if ext not in KB_ALLOWED_EXTENSIONS:
            raise ValueError(f"不支持的文件类型: {ext or '无后缀'}。支持 {KB_ALLOWED_EXTENSIONS_LABEL}")

        contents = upload_file.file.read()
        size = len(contents)
        max_file_size = self.settings_service.get_runtime_value("kb_max_file_size")
        if size > max_file_size:
            raise ValueError(f"文件大小超过限制 {max_file_size / 1024 / 1024:.0f}MB")

        content_hash = hashlib.sha256(contents).hexdigest()
        stored_name = self._safe_stored_name(original_name)
        dir_storage = self._directory_storage_dir(directory_id)
        dir_storage.mkdir(parents=True, exist_ok=True)
        relative_path = str(Path(f"dir_{directory_id}") / stored_name)
        file_path = self.storage_path / relative_path
        file_path.write_bytes(contents)

        mime_type = upload_file.content_type or "application/octet-stream"
        file = self.store.create_file(
            directory_id=directory_id,
            original_name=original_name,
            stored_name=stored_name,
            relative_path=relative_path,
            size=size,
            mime_type=mime_type,
            created_by=created_by,
            content_hash=content_hash,
        )
        logger.info(
            "kb_file_uploaded",
            file_id=file.id,
            directory_id=directory_id,
            original_name=original_name,
            size=size,
            content_hash=content_hash,
        )

        # 自动触发单文件索引（失败不影响文件保存）
        task_id: str | None = None
        try:
            if self.settings_service.get_runtime_value("auto_index_on_upload"):
                task_id = self.index_service.trigger_file_index(file.id)
                self.store.update_file_index_status(file.id, "indexing", task_id=task_id)
                logger.info("kb_file_index_triggered", file_id=file.id, task_id=task_id)
        except Exception as exc:
            logger.warning("kb_file_index_trigger_failed", file_id=file.id, error=str(exc))

        return KbFileUploadResponse(
            file=self._to_file_out(file),
            task_id=task_id,
        )

    def _to_file_out(self, file: KbFile) -> KbFileOut:
        return KbFileOut(
            id=file.id,
            directory_id=file.directory_id,
            original_name=file.original_name,
            stored_name=file.stored_name,
            size=file.size,
            mime_type=file.mime_type,
            status=file.status,  # type: ignore[arg-type]
            task_id=file.last_task_id,
            created_at=file.created_at.isoformat() if file.created_at else None,
            updated_at=file.updated_at.isoformat() if file.updated_at else None,
        )

    def trigger_file_index(self, file_id: int) -> KbFileIndexResponse:
        file = self.store.get_file(file_id)
        if not file:
            raise ValueError("FILE_NOT_FOUND")
        if file.status == "indexing":
            raise ValueError("FILE_ALREADY_INDEXING")
        task_id = self.index_service.trigger_file_index(file_id)
        self.store.update_file_index_status(file_id, "indexing", task_id=task_id)
        logger.info("kb_file_index_manual_triggered", file_id=file_id, task_id=task_id)
        return KbFileIndexResponse(task_id=task_id)

    def list_files(self, directory_id: int) -> list[KbFileOut]:
        if not self.store.get_directory(directory_id):
            raise ValueError("DIRECTORY_NOT_FOUND")
        files = self.store.list_files(directory_id)
        return [self._to_file_out(f) for f in files]

    def _collect_descendants(self, directory_id: int) -> tuple[list[int], list[int]]:
        """返回 (dir_ids, file_ids)，包含自身及其所有后代。"""
        dir_ids = [directory_id]
        file_ids = [f.id for f in self.store.list_files(directory_id)]
        for child in self.store.list_children(directory_id):
            child_dir_ids, child_file_ids = self._collect_descendants(child.id)
            dir_ids.extend(child_dir_ids)
            file_ids.extend(child_file_ids)
        return dir_ids, file_ids

    def delete_directory(self, directory_id: int) -> tuple[int, int]:
        if not self.store.get_directory(directory_id):
            raise ValueError("DIRECTORY_NOT_FOUND")

        dir_ids, file_ids = self._collect_descendants(directory_id)

        # 先删除物理文件
        for file_id in file_ids:
            file = self.store.get_file(file_id)
            if file:
                self._unlink_file(file.relative_path)

        # 再删除物理目录（包含空目录）
        for dir_id in dir_ids:
            self._rmdir_storage(dir_id)

        # 最后级联删除数据库记录
        self.store.delete_directory(directory_id)

        logger.info(
            "kb_directory_deleted",
            directory_id=directory_id,
            deleted_files=len(file_ids),
            deleted_directories=len(dir_ids),
        )
        return len(file_ids), len(dir_ids)

    def delete_file(self, file_id: int) -> bool:
        file = self.store.get_file(file_id)
        if not file:
            raise ValueError("FILE_NOT_FOUND")
        self._unlink_file(file.relative_path)
        self.store.delete_file(file_id)
        logger.info("kb_file_deleted", file_id=file_id, original_name=file.original_name)
        return True

    def trigger_rebuild(self, kb_id: str = "default") -> str:
        task_id = self.index_service.trigger_rebuild(kb_id=kb_id)
        logger.info("kb_trigger_rebuild", task_id=task_id, kb_id=kb_id)
        return task_id

    def trigger_graph_rebuild(self, directory_id: int) -> KbRebuildGraphResponse:
        task_id = self.index_service.trigger_graph_rebuild(kb_id=str(directory_id))
        logger.info("kb_trigger_graph_rebuild", directory_id=directory_id, task_id=task_id)
        return KbRebuildGraphResponse(task_id=task_id)
