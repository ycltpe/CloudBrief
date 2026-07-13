import os
from contextlib import asynccontextmanager

import numpy as np
from fastapi import FastAPI
from pydantic import BaseModel
from sentence_transformers import CrossEncoder


class RerankRequest(BaseModel):
    model: str
    query: str
    documents: list[str]
    top_n: int | None = None


class RerankResult(BaseModel):
    index: int
    relevance_score: float


class RerankResponse(BaseModel):
    results: list[RerankResult]


MODEL_NAME = os.getenv("RERANK_MODEL", "BAAI/bge-reranker-large")
cross_encoder: CrossEncoder | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global cross_encoder
    cross_encoder = CrossEncoder(MODEL_NAME)
    yield
    cross_encoder = None


app = FastAPI(title="Local Reranker", lifespan=lifespan)


@app.post("/rerank", response_model=RerankResponse)
async def rerank(req: RerankRequest):
    pairs = [[req.query, doc] for doc in req.documents]
    scores: np.ndarray = cross_encoder.predict(pairs)
    indexed = sorted(enumerate(scores.tolist()), key=lambda x: x[1], reverse=True)
    if req.top_n is not None:
        indexed = indexed[: req.top_n]
    return RerankResponse(
        results=[
            RerankResult(index=idx, relevance_score=float(score))
            for idx, score in indexed
        ]
    )


@app.get("/health")
async def health():
    return {"status": "ok"}
