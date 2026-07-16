from abc import ABC, abstractmethod
from typing import Any

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.config import Settings
from app.services.settings_service import SettingsService

_RETRY_CONDITION = retry_if_exception_type(
    (httpx.NetworkError, httpx.TimeoutException, httpx.ConnectError)
)
_RETRY_STOP = stop_after_attempt(3)
_RETRY_WAIT = wait_exponential(multiplier=1, min=1, max=10)


class RerankerAdapter(ABC):
    """重排模型统一抽象，支持 DashScope 与本地 vLLM/TEI 等 OpenAI/Cohere 兼容端点。"""

    @abstractmethod
    def rerank(
        self,
        query: str,
        passages: list[str],
        top_n: int | None = None,
    ) -> list[tuple[int, float]]:
        """返回 (原始下标, 相关性分数) 列表，按分数降序。"""
        ...

    @abstractmethod
    def close(self) -> None:
        """释放底层 HTTP 客户端资源。"""
        ...


class DashScopeReranker(RerankerAdapter):
    """DashScope qwen3-rerank 实现，使用 OpenAI-compatible /reranks 端点。"""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        timeout: float,
    ):
        self._model = model
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            timeout=timeout,
            headers={"Authorization": f"Bearer {api_key}"},
        )

    @retry(stop=_RETRY_STOP, wait=_RETRY_WAIT, retry=_RETRY_CONDITION)
    def rerank(
        self,
        query: str,
        passages: list[str],
        top_n: int | None = None,
    ) -> list[tuple[int, float]]:
        payload: dict[str, Any] = {
            "model": self._model,
            "query": query,
            "documents": passages,
        }
        if top_n is not None:
            payload["top_n"] = top_n

        response = self._client.post("/reranks", json=payload)
        response.raise_for_status()
        data = response.json()

        results = data.get("data", []) or data.get("results", [])
        return [(int(r["index"]), float(r["relevance_score"])) for r in results]

    def close(self) -> None:
        self._client.close()


class LocalReranker(RerankerAdapter):
    """本地 reranker 实现，适配 vLLM / TEI 等 Cohere-compatible /rerank 端点。"""

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        timeout: float,
    ):
        self._model = model
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            timeout=timeout,
        )

    @retry(stop=_RETRY_STOP, wait=_RETRY_WAIT, retry=_RETRY_CONDITION)
    def rerank(
        self,
        query: str,
        passages: list[str],
        top_n: int | None = None,
    ) -> list[tuple[int, float]]:
        payload: dict[str, Any] = {
            "model": self._model,
            "query": query,
            "documents": passages,
        }
        if top_n is not None:
            payload["top_n"] = top_n

        response = self._client.post("/rerank", json=payload)
        response.raise_for_status()
        data = response.json()

        # vLLM / TEI 返回 Cohere-compatible 格式：results 列表
        results = data.get("results", []) or data.get("data", [])
        return [(int(r["index"]), float(r["relevance_score"])) for r in results]

    def close(self) -> None:
        self._client.close()


def create_reranker_adapter(
    settings: Settings,
    settings_service: SettingsService,
) -> RerankerAdapter:
    """根据运行期配置创建对应的重排适配器（DB 配置优先于 .env 默认值）。"""
    provider = settings_service.get_runtime_value("reranker_provider")
    timeout = settings_service.get_runtime_value("request_timeout")

    if provider == "dashscope":
        return DashScopeReranker(
            base_url=str(settings_service.get_runtime_value("rerank_base_url")),
            api_key=settings_service.get_runtime_value("reranker_api_key"),
            model=settings_service.get_runtime_value("reranker_model"),
            timeout=timeout,
        )

    return LocalReranker(
        base_url=settings_service.get_runtime_value("local_reranker_url"),
        model=settings_service.get_runtime_value("local_reranker_model"),
        timeout=timeout,
    )
