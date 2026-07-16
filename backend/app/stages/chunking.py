import re

from pydantic import BaseModel

from app.stages.base import AbstractStage, Chunk, Document


class ChunkingInput(BaseModel):
    documents: list[Document]


class ChunkingOutput(BaseModel):
    chunks: list[Chunk]


class ChunkingStage(AbstractStage[ChunkingInput, ChunkingOutput]):
    """按知识源类型切分片段，保证语义相对完整。"""

    def __init__(self, max_chars: int = 800, overlap_chars: int = 100):
        self.max_chars = max_chars
        self.overlap_chars = overlap_chars

    @property
    def name(self) -> str:
        return "chunking"

    def execute(self, input_data: ChunkingInput) -> ChunkingOutput:
        chunks: list[Chunk] = []
        for doc in input_data.documents:
            doc_chunks = self._split_document(doc)
            for idx, text in enumerate(doc_chunks):
                content = text.strip()
                # 空 chunk 会让 Embedding API 整批拒绝（输入长度下限为 1），直接丢弃
                if not content:
                    continue
                chunks.append(
                    Chunk(
                        chunk_id=f"{doc.source_type}:{doc.source_id}:{idx}",
                        content=content,
                        source_type=doc.source_type,
                        title=doc.title,
                        updated_at=doc.updated_at,
                        source_id=doc.source_id,
                        chunk_index=idx,
                    )
                )
        return ChunkingOutput(chunks=chunks)

    def _split_document(self, doc: Document) -> list[str]:
        # ticket / faq 通常较短，直接作为一个 chunk；超长时同样硬切
        if doc.source_type in ("ticket", "faq"):
            return self._hard_split(doc.content)

        # help_doc / changelog 按段落 + 长度限制切分
        paragraphs = re.split(r"\n\s*\n", doc.content)
        paragraphs = [p.strip() for p in paragraphs if p.strip()]
        # 单个段落超过 max_chars 时强制硬切（扫描件 OCR 文本等无空行分段场景），
        # 否则超长段落会原样进入 Embedding 请求，超出模型输入上限
        paragraphs = [piece for p in paragraphs for piece in self._hard_split(p)]
        return self._merge_paragraphs(paragraphs)

    def _hard_split(self, text: str) -> list[str]:
        """超过 max_chars 的文本按 max_chars 窗口 + overlap_chars 重叠强制切分。"""
        if len(text) <= self.max_chars:
            return [text]
        pieces: list[str] = []
        step = max(self.max_chars - self.overlap_chars, 1)
        for start in range(0, len(text), step):
            piece = text[start : start + self.max_chars]
            if piece.strip():
                pieces.append(piece)
        return pieces

    def _merge_paragraphs(self, paragraphs: list[str]) -> list[str]:
        chunks: list[str] = []
        current: list[str] = []
        current_len = 0

        for para in paragraphs:
            para_len = len(para)
            if current and current_len + para_len > self.max_chars:
                chunks.append("\n\n".join(current))
                # 重叠：保留最后一部分
                overlap_text = ""
                for prev in reversed(current):
                    if len(overlap_text) + len(prev) > self.overlap_chars:
                        break
                    overlap_text = prev + ("\n\n" + overlap_text if overlap_text else "")
                current = [overlap_text] if overlap_text else []
                current_len = len(overlap_text)
            current.append(para)
            current_len += para_len + 2

        if current:
            chunks.append("\n\n".join(current))
        return chunks
