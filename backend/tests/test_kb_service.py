from unittest.mock import MagicMock

import pytest

from app.services.kb_service import KbService
from app.stores.db import KbDirectory, KbFile


class _FakeUploadFile:
    def __init__(self, filename: str, content: bytes, content_type: str = "text/markdown"):
        self.filename = filename
        self.content_type = content_type
        self.file = MagicMock()
        self.file.read.return_value = content


def _make_kb_file(file_id: int = 1, status: str = "uploaded") -> KbFile:
    f = KbFile(
        id=file_id,
        directory_id=1,
        original_name="test.md",
        stored_name="test_abc123.md",
        relative_path="dir_1/test_abc123.md",
        size=12,
        mime_type="text/markdown",
        status=status,
    )
    f.last_task_id = None
    return f


def test_upload_file_triggers_index_when_auto_enabled(tmp_path, monkeypatch):
    store = MagicMock()
    store.get_directory.return_value = KbDirectory(id=1, name="docs")
    store.create_file.return_value = _make_kb_file(1, "uploaded")

    index_service = MagicMock()
    index_service.trigger_file_index.return_value = "task-123"

    settings_service = MagicMock()
    settings_service.get_runtime_value.return_value = True

    svc = KbService(store=store, index_service=index_service, settings_service=settings_service)
    monkeypatch.setattr(svc, "storage_path", tmp_path)

    upload = _FakeUploadFile("hello.md", b"# Hello")
    result = svc.upload_file(directory_id=1, upload_file=upload)

    assert result.task_id == "task-123"
    assert result.file.status == "uploaded"
    index_service.trigger_file_index.assert_called_once_with(1)
    store.update_file_index_status.assert_called_once_with(1, "indexing", task_id="task-123")


def test_upload_file_does_not_trigger_index_when_disabled(tmp_path, monkeypatch):
    store = MagicMock()
    store.get_directory.return_value = KbDirectory(id=1, name="docs")
    store.create_file.return_value = _make_kb_file(2, "uploaded")

    index_service = MagicMock()
    settings_service = MagicMock()
    settings_service.get_runtime_value.return_value = False

    svc = KbService(store=store, index_service=index_service, settings_service=settings_service)
    monkeypatch.setattr(svc, "storage_path", tmp_path)

    upload = _FakeUploadFile("hello.md", b"# Hello")
    result = svc.upload_file(directory_id=1, upload_file=upload)

    assert result.task_id is None
    index_service.trigger_file_index.assert_not_called()


def test_to_file_out_maps_task_id():
    f = _make_kb_file(3, "indexed")
    f.last_task_id = "task-456"
    f.updated_at = None

    svc = KbService()
    out = svc._to_file_out(f)

    assert out.task_id == "task-456"
    assert out.status == "indexed"


def test_trigger_file_index_rejects_indexing_file():
    store = MagicMock()
    store.get_file.return_value = _make_kb_file(4, "indexing")

    svc = KbService(store=store)
    with pytest.raises(ValueError, match="FILE_ALREADY_INDEXING"):
        svc.trigger_file_index(4)


def test_trigger_file_index_success():
    store = MagicMock()
    store.get_file.return_value = _make_kb_file(5, "uploaded")

    index_service = MagicMock()
    index_service.trigger_file_index.return_value = "task-789"

    svc = KbService(store=store, index_service=index_service)
    result = svc.trigger_file_index(5)

    assert result.task_id == "task-789"
    store.update_file_index_status.assert_called_once_with(5, "indexing", task_id="task-789")


def test_upload_file_keeps_file_when_index_trigger_fails(tmp_path, monkeypatch):
    store = MagicMock()
    store.get_directory.return_value = KbDirectory(id=1, name="docs")
    store.create_file.return_value = _make_kb_file(6, "uploaded")

    index_service = MagicMock()
    index_service.trigger_file_index.side_effect = RuntimeError("broker down")

    settings_service = MagicMock()
    settings_service.get_runtime_value.return_value = True

    svc = KbService(store=store, index_service=index_service, settings_service=settings_service)
    monkeypatch.setattr(svc, "storage_path", tmp_path)

    upload = _FakeUploadFile("hello.md", b"# Hello")
    result = svc.upload_file(directory_id=1, upload_file=upload)

    assert result.file.status == "uploaded"
    assert result.task_id is None
    store.update_file_index_status.assert_not_called()


def _make_upload_service(tmp_path, monkeypatch) -> KbService:
    store = MagicMock()
    store.get_directory.return_value = KbDirectory(id=1, name="docs")
    store.create_file.return_value = _make_kb_file(7, "uploaded")

    settings_service = MagicMock()
    settings_service.get_runtime_value.return_value = False

    svc = KbService(store=store, index_service=MagicMock(), settings_service=settings_service)
    monkeypatch.setattr(svc, "storage_path", tmp_path)
    return svc


def test_upload_file_accepts_office_formats(tmp_path, monkeypatch):
    svc = _make_upload_service(tmp_path, monkeypatch)
    for name in ("产品手册.pdf", "客服SOP.docx", "FAQ汇总.xlsx"):
        result = svc.upload_file(directory_id=1, upload_file=_FakeUploadFile(name, b"binary"))
        assert result.file.status == "uploaded"


def test_upload_file_rejects_legacy_doc_xls_with_guidance(tmp_path, monkeypatch):
    svc = _make_upload_service(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="另存"):
        svc.upload_file(directory_id=1, upload_file=_FakeUploadFile("旧文档.doc", b"x"))
    with pytest.raises(ValueError, match="另存"):
        svc.upload_file(directory_id=1, upload_file=_FakeUploadFile("旧表格.xls", b"x"))


def test_upload_file_rejects_unknown_extension(tmp_path, monkeypatch):
    svc = _make_upload_service(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="不支持的文件类型"):
        svc.upload_file(directory_id=1, upload_file=_FakeUploadFile("evil.exe", b"x"))
