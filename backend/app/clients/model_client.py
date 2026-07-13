import time
from collections.abc import AsyncIterator
from typing import Any

import httpx
import structlog
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.config import Settings

logger = structlog.get_logger()

_RETRY_CONDITION = retry_if_exception_type(
    (httpx.NetworkError, httpx.TimeoutException, httpx.ConnectError)
)
_RETRY_STOP = stop_after_attempt(3)
_RETRY_WAIT = wait_exponential(multiplier=1, min=1, max=10)


class _ProviderClient:
    """单个 provider 的同步/异步 HTTP 客户端封装。"""

    def __init__(self, base_url: str, api_key: str | None, timeout: float):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        headers = {}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        self._sync_client = httpx.Client(
            base_url=self.base_url,
            timeout=timeout,
            headers=headers,
        )
        self._async_client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=timeout,
            headers=headers,
        )

    def close(self) -> None:
        self._sync_client.close()

    async def aclose(self) -> None:
        await self._async_client.aclose()


class ModelClient:
    """统一封装 Embedding / Rerank / LLM 调用，集中管理密钥、重试、超时、日志。

    支持主 provider（DashScope）失败后降级到本地 vLLM/Ollama 备用 provider。
    """

    def __init__(self, settings: Settings):
        self.settings = settings
        self.timeout = settings.request_timeout

        self.primary = _ProviderClient(
            base_url=str(settings.model_base_url),
            api_key=settings.dashscope_api_key.get_secret_value(),
            timeout=settings.request_timeout,
        )
        self.secondary: _ProviderClient | None = None
        if settings.llm_provider == "local" or settings.local_llm_url:
            # 本地 provider 通常不需要 api_key，或 api_key 为占位值
            self.secondary = _ProviderClient(
                base_url=settings.local_llm_url,
                api_key=None,
                timeout=settings.request_timeout,
            )

    def _get_clients(self) -> list[_ProviderClient]:
        clients = [self.primary]
        if self.secondary:
            clients.append(self.secondary)
        return clients

    def _log_call(
        self,
        operation: str,
        latency_ms: float,
        tokens: int | None = None,
        error: str | None = None,
        provider: str = "primary",
    ) -> None:
        extra = {"latency_ms": round(latency_ms, 2), "provider": provider}
        if tokens is not None:
            extra["token_usage"] = tokens
        if error is not None:
            extra["error"] = error
            logger.warning(f"{operation}_failed", **extra)
        else:
            logger.info(f"{operation}_success", **extra)

    @retry(stop=_RETRY_STOP, wait=_RETRY_WAIT, retry=_RETRY_CONDITION)
    def _embed_with_client(
        self,
        client: _ProviderClient,
        texts: list[str],
        model: str,
    ) -> list[list[float]]:
        response = client._sync_client.post(
            "/embeddings",
            json={"model": model, "input": texts},
        )
        response.raise_for_status()
        data = response.json()
        return [item["embedding"] for item in data["data"]]

    def embed(self, texts: list[str], model: str | None = None) -> list[list[float]]:
        start = time.perf_counter()
        primary_model = model or self.settings.embedding_model
        secondary_model = self.settings.local_embedding_model

        try:
            embeddings = self._embed_with_client(self.primary, texts, primary_model)
            self._log_call("embed", (time.perf_counter() - start) * 1000, provider="primary")
            return embeddings
        except Exception as exc:
            self._log_call(
                "embed",
                (time.perf_counter() - start) * 1000,
                error=str(exc),
                provider="primary",
            )
            if not self.secondary:
                raise

        start_secondary = time.perf_counter()
        try:
            embeddings = self._embed_with_client(self.secondary, texts, secondary_model)
            self._log_call(
                "embed",
                (time.perf_counter() - start_secondary) * 1000,
                provider="secondary",
            )
            return embeddings
        except Exception as exc:
            self._log_call(
                "embed",
                (time.perf_counter() - start_secondary) * 1000,
                error=str(exc),
                provider="secondary",
            )
            raise

    async def chat(
        self,
        messages: list[dict[str, str]],
        stream: bool = False,
        temperature: float = 0.3,
        max_tokens: int | None = None,
        timeout: float | None = None,
    ) -> str | AsyncIterator[str]:
        start = time.perf_counter()
        request_timeout = timeout if timeout is not None else self.timeout

        primary_model = self.settings.llm_model
        secondary_model = self.settings.local_llm_model

        payload = {
            "model": primary_model,
            "messages": messages,
            "stream": stream,
            "temperature": temperature,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens

        try:
            result = await self._chat_with_payload(
                self.primary,
                payload,
                stream=stream,
                timeout=request_timeout,
            )
            self._log_call("chat", (time.perf_counter() - start) * 1000, provider="primary")
            return result
        except Exception as exc:
            self._log_call("chat", (time.perf_counter() - start) * 1000, error=str(exc), provider="primary")
            if not self.secondary:
                raise

        start_secondary = time.perf_counter()
        payload["model"] = secondary_model
        try:
            result = await self._chat_with_payload(
                self.secondary,
                payload,
                stream=stream,
                timeout=request_timeout,
            )
            self._log_call("chat", (time.perf_counter() - start_secondary) * 1000, provider="secondary")
            return result
        except Exception as exc:
            self._log_call(
                "chat",
                (time.perf_counter() - start_secondary) * 1000,
                error=str(exc),
                provider="secondary",
            )
            raise

    async def _chat_with_payload(
        self,
        client: _ProviderClient,
        payload: dict[str, Any],
        stream: bool,
        timeout: float,
    ) -> str | AsyncIterator[str]:
        if not stream:
            response = await client._async_client.post(
                "/chat/completions",
                json=payload,
                timeout=timeout,
            )
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"]

        async def _stream() -> AsyncIterator[str]:
            async with client._async_client.stream(
                "POST",
                "/chat/completions",
                json=payload,
                timeout=timeout,
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data = line[6:]
                    if data == "[DONE]":
                        break
                    import json

                    chunk = json.loads(data)
                    choices = chunk.get("choices", [])
                    if not choices:
                        continue
                    delta = choices[0].get("delta", {}).get("content")
                    if delta:
                        yield delta

        return _stream()

    def close(self) -> None:
        self.primary.close()
        if self.secondary:
            self.secondary.close()

    async def aclose(self) -> None:
        await self.primary.aclose()
        if self.secondary:
            await self.secondary.aclose()
