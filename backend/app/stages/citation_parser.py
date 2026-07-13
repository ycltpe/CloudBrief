import datetime
import re

from pydantic import BaseModel

from app.models.schemas import Citation
from app.stages.base import RetrievalResult


class CitationParserInput(BaseModel):
    raw_answer: str
    chunks: list[RetrievalResult]


class CitationParserOutput(BaseModel):
    clean_answer: str
    citations: list[Citation]


class CitationParserStage:
    """从 LLM 输出中提取 [^chunk_id] 引用，并重编号为 [^1]、[^^2]..."""

    _PATTERN = re.compile(r"\[\^([^\]]+)\]")

    def execute(self, input_data: CitationParserInput) -> CitationParserOutput:
        chunk_map = {c.chunk_id: c for c in input_data.chunks}

        seen_ids: list[str] = []
        id_to_index: dict[str, int] = {}

        def _replace(match) -> str:
            chunk_id = match.group(1)
            if chunk_id not in id_to_index:
                id_to_index[chunk_id] = len(seen_ids) + 1
                seen_ids.append(chunk_id)
            return f"[^{id_to_index[chunk_id]}]"

        clean_answer = self._PATTERN.sub(_replace, input_data.raw_answer)

        citations: list[Citation] = []
        for chunk_id in seen_ids:
            chunk = chunk_map.get(chunk_id)
            if not chunk:
                continue
            updated_at = chunk.updated_at
            if isinstance(updated_at, datetime.datetime):
                updated_at = updated_at.isoformat()
            citations.append(
                Citation(
                    chunk_id=chunk.chunk_id,
                    source_title=chunk.title,
                    source_type=chunk.source_type,
                    updated_at=updated_at,
                    content_summary=chunk.content[:200],
                )
            )

        return CitationParserOutput(clean_answer=clean_answer, citations=citations)
