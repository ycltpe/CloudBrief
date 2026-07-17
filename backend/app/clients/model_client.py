import base64
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
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
from app.services.settings_service import SettingsService

logger = structlog.get_logger()


@dataclass
class ToolCall:
    """单次工具调用声明（OpenAI 兼容格式）。"""

    id: str
    type: str
    function: dict[str, Any]

    @property
    def name(self) -> str:
        return self.function.get("name", "")

    @property
    def arguments(self) -> str:
        return self.function.get("arguments", "")


@dataclass
class ChatCompletion:
    """LLM 非流式响应，支持文本与工具调用并存。"""

    content: str | None
    tool_calls: list[ToolCall] | None
    model: str | None = None
    usage: dict[str, Any] | None = None
    raw: dict[str, Any] | None = None

_RETRY_CONDITION = retry_if_exception_type(
    (httpx.NetworkError, httpx.TimeoutException, httpx.ConnectError)
)
_RETRY_STOP = stop_after_attempt(3)
_RETRY_WAIT = wait_exponential(multiplier=1, min=1, max=10)


def format_http_error(exc: Exception) -> str:
    """HTTP 错误附带响应体，便于定位 403/429 等平台侧原因。"""
    if isinstance(exc, httpx.HTTPStatusError):
        body = exc.response.text
        if len(body) > 500:
            body = body[:500] + "...(truncated)"
        return f"{exc} | response_body={body}"
    return str(exc)


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

    三种能力各自使用本组凭据（LLM / Embedding / OCR 的 key 与端点相互独立）。
    provider 为显式选择：=local 时本地服务为权威路径，不回退云端（避免私有化数据外发）；
    =dashscope 时保留到本地备用 provider 的失败降级。
    连接参数与模型名走运行期配置（DB → .env → 默认）：连接签名变化时自动重建客户端，
    模型名/超时每次调用实时读取。
    """

    def __init__(self, settings: Settings):
        self.settings = settings
        self._settings_service = SettingsService()
        self._clients_signature: tuple | None = None
        self.llm_primary: _ProviderClient | None = None
        self.llm_secondary: _ProviderClient | None = None
        self.embed_primary: _ProviderClient | None = None
        self.embed_secondary: _ProviderClient | None = None
        self.ocr_client: _ProviderClient | None = None
        self.timeout: float = settings.request_timeout
        self._ensure_clients()

    def _client_params(self) -> dict:
        svc = self._settings_service
        return {
            "llm_provider": str(svc.get_runtime_value("llm_provider")),
            "llm_base_url": str(svc.get_runtime_value("llm_base_url")),
            "llm_api_key": str(svc.get_runtime_value("llm_api_key") or ""),
            "local_llm_url": str(svc.get_runtime_value("local_llm_url") or ""),
            "embedding_provider": str(svc.get_runtime_value("embedding_provider")),
            "embedding_base_url": str(svc.get_runtime_value("embedding_base_url")),
            "embedding_api_key": str(svc.get_runtime_value("embedding_api_key") or ""),
            "local_embedding_url": str(svc.get_runtime_value("local_embedding_url") or ""),
            "ocr_base_url": str(svc.get_runtime_value("ocr_base_url")),
            "ocr_api_key": str(svc.get_runtime_value("ocr_api_key") or ""),
            "request_timeout": float(svc.get_runtime_value("request_timeout")),
        }

    def _all_clients(self) -> list[_ProviderClient]:
        return [
            c
            for c in (
                self.llm_primary,
                self.llm_secondary,
                self.embed_primary,
                self.embed_secondary,
                self.ocr_client,
            )
            if c is not None
        ]

    def _ensure_clients(self) -> None:
        params = self._client_params()
        signature = tuple(params.values())
        if signature == self._clients_signature:
            return
        old_clients = self._all_clients()
        self.timeout = params["request_timeout"]

        # LLM：local 为权威路径；dashscope 模式下本地端点作为失败降级
        if params["llm_provider"] == "local":
            self.llm_primary = _ProviderClient(
                base_url=params["local_llm_url"],
                api_key=None,
                timeout=params["request_timeout"],
            )
            self.llm_secondary = None
        else:
            self.llm_primary = _ProviderClient(
                base_url=params["llm_base_url"],
                api_key=params["llm_api_key"],
                timeout=params["request_timeout"],
            )
            self.llm_secondary = None
            if params["local_llm_url"]:
                # 本地 provider 通常不需要 api_key，或 api_key 为占位值
                self.llm_secondary = _ProviderClient(
                    base_url=params["local_llm_url"],
                    api_key=None,
                    timeout=params["request_timeout"],
                )

        # Embedding：本地降级端点未单独配置时回退本地 LLM 端点
        embed_local_url = params["local_embedding_url"] or params["local_llm_url"]
        if params["embedding_provider"] == "local":
            self.embed_primary = _ProviderClient(
                base_url=embed_local_url,
                api_key=None,
                timeout=params["request_timeout"],
            )
            self.embed_secondary = None
        else:
            self.embed_primary = _ProviderClient(
                base_url=params["embedding_base_url"],
                api_key=params["embedding_api_key"],
                timeout=params["request_timeout"],
            )
            self.embed_secondary = None
            if embed_local_url:
                self.embed_secondary = _ProviderClient(
                    base_url=embed_local_url,
                    api_key=None,
                    timeout=params["request_timeout"],
                )

        # OCR 仅支持云端视觉模型，使用独立凭据
        self.ocr_client = _ProviderClient(
            base_url=params["ocr_base_url"],
            api_key=params["ocr_api_key"],
            timeout=params["request_timeout"],
        )

        self._clients_signature = signature
        for client in old_clients:
            try:
                client.close()
            except Exception:
                logger.warning("model_client_close_stale_failed")

    def _log_call(
        self,
        operation: str,
        latency_ms: float,
        tokens: int | None = None,
        error: str | None = None,
        provider: str = "primary",
        model: str | None = None,
        payload_summary: dict | None = None,
    ) -> None:
        extra: dict[str, Any] = {"latency_ms": round(latency_ms, 2), "provider": provider}
        if tokens is not None:
            extra["token_usage"] = tokens
        if model is not None:
            extra["model"] = model
        if payload_summary is not None:
            extra["payload"] = payload_summary
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
        self._ensure_clients()
        start = time.perf_counter()
        svc = self._settings_service
        if svc.get_runtime_value("embedding_provider") == "local":
            primary_model = model or svc.get_runtime_value("local_embedding_model")
        else:
            primary_model = model or svc.get_runtime_value("embedding_model")
        secondary_model = svc.get_runtime_value("local_embedding_model")
        payload_summary = {"text_count": len(texts)}

        try:
            embeddings = self._embed_with_client(self.embed_primary, texts, primary_model)
            self._log_call(
                "embed",
                (time.perf_counter() - start) * 1000,
                provider="primary",
                model=primary_model,
                payload_summary=payload_summary,
            )
            return embeddings
        except Exception as exc:
            self._log_call(
                "embed",
                (time.perf_counter() - start) * 1000,
                error=format_http_error(exc),
                provider="primary",
                model=primary_model,
                payload_summary=payload_summary,
            )
            if not self.embed_secondary:
                raise

        start_secondary = time.perf_counter()
        try:
            embeddings = self._embed_with_client(self.embed_secondary, texts, secondary_model)
            self._log_call(
                "embed",
                (time.perf_counter() - start_secondary) * 1000,
                provider="secondary",
                model=secondary_model,
                payload_summary=payload_summary,
            )
            return embeddings
        except Exception as exc:
            self._log_call(
                "embed",
                (time.perf_counter() - start_secondary) * 1000,
                error=format_http_error(exc),
                provider="secondary",
                model=secondary_model,
                payload_summary=payload_summary,
            )
            raise

    async def chat(
        self,
        messages: list[dict[str, str]],
        stream: bool = False,
        temperature: float = 0.3,
        max_tokens: int | None = None,
        timeout: float | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
    ) -> str | AsyncIterator[str] | ChatCompletion:
        self._ensure_clients()
        start = time.perf_counter()
        request_timeout = timeout if timeout is not None else self._settings_service.get_runtime_value("request_timeout")

        if self._settings_service.get_runtime_value("llm_provider") == "local":
            primary_model = self._settings_service.get_runtime_value("local_llm_model")
        else:
            primary_model = self._settings_service.get_runtime_value("llm_model")
        secondary_model = self._settings_service.get_runtime_value("local_llm_model")

        payload = {
            "model": primary_model,
            "messages": messages,
            "stream": stream,
            "temperature": temperature,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens

        payload_summary = {
            "stream": stream,
            "temperature": temperature,
            "message_count": len(messages),
        }
        if max_tokens is not None:
            payload_summary["max_tokens"] = max_tokens

        if tools is not None:
            if stream:
                raise ValueError("tools are not supported with stream=True")
            payload["tools"] = tools
            if tool_choice is not None:
                payload["tool_choice"] = tool_choice
            payload_summary["tool_count"] = len(tools)
            if tool_choice is not None:
                payload_summary["tool_choice"] = tool_choice

        try:
            result = await self._chat_with_payload(
                self.llm_primary,
                payload,
                stream=stream,
                timeout=request_timeout,
            )
            self._log_call(
                "chat",
                (time.perf_counter() - start) * 1000,
                provider="primary",
                model=primary_model,
                payload_summary=payload_summary,
            )
            if tools is not None:
                return self._parse_chat_completion(result)
            return result
        except Exception as exc:
            self._log_call(
                "chat",
                (time.perf_counter() - start) * 1000,
                error=format_http_error(exc),
                provider="primary",
                model=primary_model,
                payload_summary=payload_summary,
            )
            if not self.llm_secondary:
                raise

        start_secondary = time.perf_counter()
        payload["model"] = secondary_model
        payload_summary["model_switched"] = True
        try:
            result = await self._chat_with_payload(
                self.llm_secondary,
                payload,
                stream=stream,
                timeout=request_timeout,
            )
            self._log_call(
                "chat",
                (time.perf_counter() - start_secondary) * 1000,
                provider="secondary",
                model=secondary_model,
                payload_summary=payload_summary,
            )
            if tools is not None:
                return self._parse_chat_completion(result)
            return result
        except Exception as exc:
            self._log_call(
                "chat",
                (time.perf_counter() - start_secondary) * 1000,
                error=format_http_error(exc),
                provider="secondary",
                model=secondary_model,
                payload_summary=payload_summary,
            )
            raise

    @retry(stop=_RETRY_STOP, wait=_RETRY_WAIT, retry=_RETRY_CONDITION)
    async def _chat_with_payload(
        self,
        client: _ProviderClient,
        payload: dict[str, Any],
        stream: bool,
        timeout: float,
    ) -> str | AsyncIterator[str] | dict[str, Any]:
        if not stream:
            response = await client._async_client.post(
                "/chat/completions",
                json=payload,
                timeout=timeout,
            )
            response.raise_for_status()
            data = response.json()
            if payload.get("tools"):
                return data
            return data["choices"][0]["message"]["content"]

        async def _stream() -> AsyncIterator[str]:
            start_stream = time.perf_counter()
            chunk_count = 0
            first_chunk_latency_ms = None
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
                        if first_chunk_latency_ms is None:
                            first_chunk_latency_ms = int((time.perf_counter() - start_stream) * 1000)
                            logger.info(
                                "llm_stream_first_chunk",
                                provider="primary" if client is self.llm_primary else "secondary",
                                first_chunk_latency_ms=first_chunk_latency_ms,
                            )
                        chunk_count += 1
                        yield delta
            logger.info(
                "llm_stream_done",
                provider="primary" if client is self.llm_primary else "secondary",
                chunk_count=chunk_count,
                first_chunk_latency_ms=first_chunk_latency_ms,
                total_latency_ms=int((time.perf_counter() - start_stream) * 1000),
            )

        return _stream()

    def _parse_chat_completion(self, data: dict[str, Any]) -> ChatCompletion:
        choice = data.get("choices", [{}])[0]
        message = choice.get("message", {})
        content = message.get("content")
        raw_tool_calls = message.get("tool_calls")
        tool_calls = None
        if raw_tool_calls:
            tool_calls = [
                ToolCall(
                    id=tc.get("id", ""),
                    type=tc.get("type", "function"),
                    function=tc.get("function", {}) or {},
                )
                for tc in raw_tool_calls
            ]
        return ChatCompletion(
            content=content,
            tool_calls=tool_calls,
            model=data.get("model"),
            usage=data.get("usage"),
            raw=data,
        )

    @retry(stop=_RETRY_STOP, wait=_RETRY_WAIT, retry=_RETRY_CONDITION)
    def _ocr_with_client(
        self,
        client: _ProviderClient,
        image_b64: str,
        model: str,
    ) -> str:
        response = client._sync_client.post(
            "/chat/completions",
            json={
                "model": model,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:image/png;base64,{image_b64}"},
                            },
                            {
                                "type": "text",
                                "text": "请识别并输出图片中的全部文字，保持原有段落结构，只输出文字内容本身。",
                            },
                        ],
                    }
                ],
                "temperature": 0,
            },
            timeout=self._settings_service.get_runtime_value("ocr_timeout_seconds"),
        )
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"]

    def ocr_image(self, image_bytes: bytes, model: str | None = None) -> str:
        """对单张图片（PNG 字节）做 OCR，返回识别文本。扫描件 PDF 逐页调用。"""
        self._ensure_clients()
        start = time.perf_counter()
        primary_model = model or self._settings_service.get_runtime_value("ocr_model")
        image_b64 = base64.b64encode(image_bytes).decode("ascii")
        payload_summary = {"image_bytes": len(image_bytes)}

        try:
            text = self._ocr_with_client(self.ocr_client, image_b64, primary_model)
            self._log_call(
                "ocr",
                (time.perf_counter() - start) * 1000,
                provider="primary",
                model=primary_model,
                payload_summary=payload_summary,
            )
            return text
        except Exception as exc:
            self._log_call(
                "ocr",
                (time.perf_counter() - start) * 1000,
                error=format_http_error(exc),
                provider="primary",
                model=primary_model,
                payload_summary=payload_summary,
            )
            raise

    def close(self) -> None:
        for client in self._all_clients():
            client.close()

    async def aclose(self) -> None:
        for client in self._all_clients():
            await client.aclose()
