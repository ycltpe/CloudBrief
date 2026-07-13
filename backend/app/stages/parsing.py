import csv
import json
from datetime import datetime
from pathlib import Path

import frontmatter

from app.stages.base import Document


class NativeParser:
    """Native 知识源解析器，支持 Markdown / JSON / CSV。"""

    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)

    def parse(self) -> list[Document]:
        documents: list[Document] = []
        for subdir in ["help_docs", "changelog", "tickets", "faq"]:
            path = self.data_dir / subdir
            if not path.exists():
                continue
            if subdir == "help_docs":
                documents.extend(self._parse_help_docs(path))
            elif subdir == "changelog":
                documents.extend(self._parse_changelog(path))
            elif subdir == "tickets":
                documents.extend(self._parse_tickets(path))
            elif subdir == "faq":
                documents.extend(self._parse_faq(path))

        # 管理员后台上传的知识库文件统一放在 data/kb 下
        kb_path = self.data_dir / "kb"
        if kb_path.exists():
            documents.extend(self._parse_kb(kb_path))

        return documents

    @staticmethod
    def _now() -> datetime:
        return datetime.utcnow()

    def _parse_help_docs(self, path: Path) -> list[Document]:
        docs: list[Document] = []
        for file_path in sorted(path.rglob("*.md")):
            post = frontmatter.load(file_path)
            title = post.get("title") or file_path.stem
            updated_at = self._parse_datetime(post.get("updated_at")) or self._now()
            docs.append(
                Document(
                    content=post.content.strip(),
                    source_type="help_doc",
                    title=str(title),
                    updated_at=updated_at,
                    source_id=str(file_path.relative_to(self.data_dir)),
                )
            )
        return docs

    def _parse_changelog(self, path: Path) -> list[Document]:
        docs: list[Document] = []
        for file_path in sorted(path.rglob("*.json")):
            data = json.loads(file_path.read_text(encoding="utf-8"))
            entries = data if isinstance(data, list) else [data]
            for idx, entry in enumerate(entries):
                docs.append(
                    Document(
                        content=f"{entry.get('title', '')}\n{entry.get('content', '')}".strip(),
                        source_type="changelog",
                        title=str(entry.get("title", file_path.stem)),
                        updated_at=self._parse_datetime(entry.get("date")) or self._now(),
                        source_id=f"{file_path.relative_to(self.data_dir)}#{idx}",
                    )
                )
        return docs

    def _parse_tickets(self, path: Path) -> list[Document]:
        docs: list[Document] = []
        for file_path in sorted(path.rglob("*.csv")):
            with file_path.open("r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                for idx, row in enumerate(reader):
                    content = "\n".join(f"{k}: {v}" for k, v in row.items())
                    docs.append(
                        Document(
                            content=content,
                            source_type="ticket",
                            title=f"工单 #{row.get('ticket_id', idx)}",
                            updated_at=self._parse_datetime(row.get("updated_at")) or self._now(),
                            source_id=f"{file_path.relative_to(self.data_dir)}#row_{idx}",
                        )
                    )
        return docs

    def _parse_faq(self, path: Path) -> list[Document]:
        docs: list[Document] = []
        for file_path in sorted(path.rglob("*.json")):
            data = json.loads(file_path.read_text(encoding="utf-8"))
            entries = data if isinstance(data, list) else [data]
            for idx, entry in enumerate(entries):
                q = entry.get("question", "")
                a = entry.get("answer", "")
                docs.append(
                    Document(
                        content=f"Q: {q}\nA: {a}".strip(),
                        source_type="faq",
                        title=q or file_path.stem,
                        updated_at=self._parse_datetime(entry.get("updated_at")) or self._now(),
                        source_id=f"{file_path.relative_to(self.data_dir)}#{idx}",
                    )
                )
        return docs

    def parse_file(self, file_path: Path) -> list[Document]:
        """解析单个知识库文件，返回一个或多个 Document。"""
        file_path = Path(file_path)
        suffix = file_path.suffix.lower()
        if suffix not in {".md", ".json", ".csv", ".txt"}:
            return []

        try:
            if suffix == ".md":
                post = frontmatter.load(file_path)
                content = post.content.strip()
                title = post.get("title") or file_path.stem
            elif suffix == ".json":
                data = json.loads(file_path.read_text(encoding="utf-8"))
                entries = data if isinstance(data, list) else [data]
                return [
                    Document(
                        content=json.dumps(entry, ensure_ascii=False),
                        source_type="kb_doc",
                        title=file_path.stem,
                        updated_at=self._now(),
                        source_id=str(file_path.relative_to(self.data_dir)),
                    )
                    for entry in entries
                ]
            elif suffix == ".csv":
                rows: list[str] = []
                with file_path.open("r", encoding="utf-8", newline="") as f:
                    reader = csv.DictReader(f)
                    for idx, row in enumerate(reader):
                        rows.append("\n".join(f"{k}: {v}" for k, v in row.items()))
                content = "\n\n".join(rows)
                title = file_path.stem
            else:  # .txt
                content = file_path.read_text(encoding="utf-8").strip()
                title = file_path.stem
        except Exception:
            return []

        relative = file_path.relative_to(self.data_dir)
        source_type = "kb_doc"
        parts = relative.parts
        if len(parts) > 2:
            source_type = f"kb_{parts[1]}"

        return [
            Document(
                content=content,
                source_type=source_type,
                title=str(title),
                updated_at=self._now(),
                source_id=str(relative),
            )
        ]

    def _parse_kb(self, kb_root: Path) -> list[Document]:
        """解析管理员后台上传的知识库文件（data/kb 下任意子目录）。"""
        docs: list[Document] = []
        for file_path in sorted(kb_root.rglob("*")):
            if file_path.is_dir():
                continue
            docs.extend(self.parse_file(file_path))
        return docs

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
