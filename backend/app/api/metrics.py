import asyncio
import time

from fastapi import APIRouter, Depends, Response
from prometheus_client import CONTENT_TYPE_LATEST

from app.clients.model_client import ModelClient
from app.config import get_settings
from app.dependencies import require_role
from app.metrics import MODEL_UP, metrics_response
from app.models.schemas import UserOut
from app.services.settings_service import SettingsService

router = APIRouter(tags=["metrics"])


@router.get("/metrics")
async def metrics(
    _current_user: UserOut = Depends(require_role("admin")),
):
    return Response(content=metrics_response(), media_type=CONTENT_TYPE_LATEST)


@router.get("/health/models")
async def health_models():
    """探测 Embedding / Rerank / LLM 三个模型的可用性。"""
    settings = get_settings()
    settings_service = SettingsService()
    model_client = ModelClient(settings)
    results = {}
    start = time.perf_counter()
    try:
        # Embedding 探测
        try:
            loop = asyncio.get_event_loop()
            await asyncio.wait_for(
                loop.run_in_executor(None, lambda: model_client.embed(["healthcheck"])),
                timeout=10,
            )
            results["embed"] = {"up": True}
            MODEL_UP.labels(provider=settings_service.get_runtime_value("llm_provider"), model="embed").set(1)
        except Exception as exc:
            results["embed"] = {"up": False, "error": str(exc)}
            MODEL_UP.labels(provider=settings_service.get_runtime_value("llm_provider"), model="embed").set(0)

        # LLM 探测
        try:
            await asyncio.wait_for(
                model_client.chat([{"role": "user", "content": "hi"}]),
                timeout=10,
            )
            results["llm"] = {"up": True}
            MODEL_UP.labels(provider=settings_service.get_runtime_value("llm_provider"), model="llm").set(1)
        except Exception as exc:
            results["llm"] = {"up": False, "error": str(exc)}
            MODEL_UP.labels(provider=settings_service.get_runtime_value("llm_provider"), model="llm").set(0)

        # Rerank 探测
        try:
            from app.stages.adapters.reranker_adapter import create_reranker_adapter

            reranker = create_reranker_adapter(settings, SettingsService())
            await asyncio.wait_for(
                reranker.rerank("hi", [{"content": "hello"}]),
                timeout=10,
            )
            results["rerank"] = {"up": True}
            MODEL_UP.labels(provider=settings_service.get_runtime_value("reranker_provider") or "unknown", model="rerank").set(1)
        except Exception as exc:
            results["rerank"] = {"up": False, "error": str(exc)}
            MODEL_UP.labels(provider=settings_service.get_runtime_value("reranker_provider") or "unknown", model="rerank").set(0)

        return {
            "healthy": all(r["up"] for r in results.values()),
            "latency_ms": int((time.perf_counter() - start) * 1000),
            "details": results,
        }
    finally:
        await model_client.aclose()
