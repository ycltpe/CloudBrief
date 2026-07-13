import pickle
from pathlib import Path

import jieba
from rank_bm25 import BM25Okapi

from app.stages.base import Chunk


class BM25Store:
    """基于 rank-bm25 + jieba 中文分词的 BM25 索引。"""

    def __init__(self, index_path: Path):
        self.index_path = Path(index_path)
        self._chunks: list[Chunk] = []
        self._chunk_ids: list[str] = []
        self._bm25: BM25Okapi | None = None

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        return list(jieba.cut_for_search(text))

    def build_index(self, chunks: list[Chunk]) -> None:
        self._chunks = chunks
        self._chunk_ids = [c.chunk_id for c in chunks]
        tokenized_corpus = [self._tokenize(c.content) for c in chunks]
        self._bm25 = BM25Okapi(tokenized_corpus)

    def save(self) -> None:
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        with self.index_path.open("wb") as f:
            pickle.dump(
                {
                    "chunks": self._chunks,
                    "chunk_ids": self._chunk_ids,
                    "bm25": self._bm25,
                },
                f,
            )

    def load(self) -> None:
        with self.index_path.open("rb") as f:
            data = pickle.load(f)
        self._chunks = data["chunks"]
        self._chunk_ids = data["chunk_ids"]
        self._bm25 = data["bm25"]

    def search(self, query: str, top_k: int = 50) -> list[tuple[str, float]]:
        if self._bm25 is None:
            raise RuntimeError("BM25 index not loaded")
        tokenized_query = self._tokenize(query)
        scores = self._bm25.get_scores(tokenized_query)
        indexed_scores = list(enumerate(scores))
        indexed_scores.sort(key=lambda x: x[1], reverse=True)
        return [(self._chunk_ids[idx], float(score)) for idx, score in indexed_scores[:top_k]]

    def get_chunk(self, chunk_id: str) -> Chunk | None:
        for chunk in self._chunks:
            if chunk.chunk_id == chunk_id:
                return chunk
        return None
