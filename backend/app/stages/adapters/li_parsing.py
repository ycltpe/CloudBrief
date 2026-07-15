from datetime import datetime
from pathlib import Path

from llama_index.core import SimpleDirectoryReader

from app.stages.base import Document


class LlamaIndexParserAdapter:
    """LlamaIndex 解析适配器，输出与 NativeParser 同结构的 Document DTO。"""

    SOURCE_TYPE_MAP = {
        "help_docs": "help_doc",
        "changelog": "changelog",
        "tickets": "ticket",
        "faq": "faq",
    }

    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)

    def parse(self, on_progress=None) -> list[Document]:
        reader = SimpleDirectoryReader(
            input_dir=str(self.data_dir),
            recursive=True,
            filename_as_id=True,
        )
        return self._to_documents(reader.load_data(), fallback_base=self.data_dir)

    def _parse_kb(self, kb_root: Path, on_progress=None) -> list[Document]:
        """只解析指定知识库目录下的文件，与 NativeParser._parse_kb 同语义。"""
        reader = SimpleDirectoryReader(
            input_dir=str(kb_root),
            recursive=True,
            filename_as_id=True,
        )
        return self._to_documents(reader.load_data(), fallback_base=Path(kb_root))

    def parse_file(self, file_path: Path, on_progress=None) -> list[Document]:
        """解析单个文件，与 NativeParser.parse_file 同语义（on_progress 仅 Native 支持）。"""
        file_path = Path(file_path)
        reader = SimpleDirectoryReader(input_files=[str(file_path)], filename_as_id=True)
        return self._to_documents(reader.load_data(), fallback_base=file_path.parent)

    def _to_documents(self, llama_docs, fallback_base: Path) -> list[Document]:
        """llama_index Document 列表统一转 DTO；source_id 取相对 data_dir 路径。"""
        results: list[Document] = []
        for doc in llama_docs:
            raw_path = Path(doc.metadata.get("file_path", doc.id_))
            try:
                relative_path = raw_path.relative_to(self.data_dir)
            except ValueError:
                try:
                    relative_path = raw_path.relative_to(fallback_base)
                except ValueError:
                    relative_path = Path(raw_path.name)
            results.append(
                Document(
                    content=doc.text,
                    source_type=self._infer_source_type(relative_path),
                    title=str(doc.metadata.get("title") or relative_path.stem),
                    updated_at=self._parse_datetime(doc.metadata.get("updated_at"))
                    or datetime.utcnow(),
                    source_id=str(relative_path),
                )
            )
        return results

    def _infer_source_type(self, relative_path: Path) -> str:
        parts = relative_path.parts
        for part in parts:
            if part in self.SOURCE_TYPE_MAP:
                return self.SOURCE_TYPE_MAP[part]
        return "help_doc"

    def _parse_datetime(self, value) -> datetime | None:
        if not value:
            return None
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
                try:
                    return datetime.strptime(value, fmt)
                except ValueError:
                    continue
        return None
