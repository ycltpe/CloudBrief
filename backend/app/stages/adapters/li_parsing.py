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

    def parse(self) -> list[Document]:
        reader = SimpleDirectoryReader(
            input_dir=str(self.data_dir),
            recursive=True,
            filename_as_id=True,
        )
        llama_docs = reader.load_data()

        results: list[Document] = []
        for doc in llama_docs:
            relative_path = Path(doc.metadata.get("file_path", doc.id_)).relative_to(
                self.data_dir
            )
            source_type = self._infer_source_type(relative_path)
            title = doc.metadata.get("title") or relative_path.stem
            updated_at = self._parse_datetime(doc.metadata.get("updated_at"))

            results.append(
                Document(
                    content=doc.text,
                    source_type=source_type,
                    title=str(title),
                    updated_at=updated_at or datetime.utcnow(),
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
