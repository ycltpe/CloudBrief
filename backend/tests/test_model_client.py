from unittest.mock import AsyncMock, MagicMock

import httpx

from app.clients.model_client import ModelClient
from app.config import get_settings


def _runtime_values(**overrides) -> dict:
    values = {
        "llm_provider": "dashscope",
        "llm_base_url": "https://llm.example.com/v1",
        "llm_api_key": "llm-key",
        "local_llm_url": "",
        "embedding_provider": "dashscope",
        "embedding_base_url": "https://embed.example.com/v1",
        "embedding_api_key": "embed-key",
        "local_embedding_url": "",
        "ocr_base_url": "https://ocr.example.com/v1",
        "ocr_api_key": "ocr-key",
        "request_timeout": 30,
        "llm_model": "qwen-plus",
        "local_llm_model": "Qwen/local-llm",
        "embedding_model": "text-embedding-v3",
        "local_embedding_model": "BAAI/bge-m3",
        "ocr_model": "qwen-vl-ocr-latest",
        "ocr_timeout_seconds": 120.0,
    }
    values.update(overrides)
    return values


def _make_client(monkeypatch, **overrides) -> tuple[ModelClient, dict]:
    """构造 ModelClient 并把运行期配置替换为固定快照。"""
    client = ModelClient(get_settings())
    values = _runtime_values(**overrides)
    monkeypatch.setattr(
        client._settings_service,
        "get_runtime_value",
        lambda key: values.get(key),
    )
    client._ensure_clients()
    return client, values


def test_ocr_image_posts_multimodal_payload(monkeypatch):
    client, _ = _make_client(monkeypatch)
    fake_response = MagicMock()
    fake_response.json.return_value = {"choices": [{"message": {"content": "识别结果文字"}}]}
    fake_sync = MagicMock()
    fake_sync.post.return_value = fake_response
    monkeypatch.setattr(client.ocr_client, "_sync_client", fake_sync)

    text = client.ocr_image(b"\x89PNG fake-bytes")

    assert text == "识别结果文字"
    call = fake_sync.post.call_args
    assert call.args[0] == "/chat/completions"
    payload = call.kwargs["json"]
    assert payload["model"] == "qwen-vl-ocr-latest"
    assert payload["temperature"] == 0
    content = payload["messages"][0]["content"]
    assert content[0]["type"] == "image_url"
    assert content[0]["image_url"]["url"].startswith("data:image/png;base64,")
    assert content[1]["type"] == "text"


def test_per_capability_credentials(monkeypatch):
    """三种能力各自使用本组 key 与端点，互不共享。"""
    client, _ = _make_client(monkeypatch)

    assert client.llm_primary.base_url == "https://llm.example.com/v1"
    assert client.llm_primary.api_key == "llm-key"
    assert client.embed_primary.base_url == "https://embed.example.com/v1"
    assert client.embed_primary.api_key == "embed-key"
    assert client.ocr_client.base_url == "https://ocr.example.com/v1"
    assert client.ocr_client.api_key == "ocr-key"
    client.close()


def test_clients_rebuilt_when_runtime_config_changes(monkeypatch):
    """DB 覆盖的连接参数变化后,下一次调用必须重建底层客户端。"""
    client, values = _make_client(monkeypatch)

    first_primary = client.llm_primary
    assert first_primary.base_url == "https://llm.example.com/v1"
    assert first_primary.api_key == "llm-key"
    assert client.llm_secondary is None

    # 签名未变化时不重建
    client._ensure_clients()
    assert client.llm_primary is first_primary

    # 连接参数变化后重建
    values["llm_api_key"] = "key-b"
    client._ensure_clients()
    assert client.llm_primary is not first_primary
    assert client.llm_primary.api_key == "key-b"
    client.close()


def test_dashscope_provider_keeps_local_fallback(monkeypatch):
    """云端模式下配置了本地端点时保留失败降级。"""
    client, _ = _make_client(monkeypatch, local_llm_url="http://127.0.0.1:8000/v1")

    assert client.llm_primary.base_url == "https://llm.example.com/v1"
    assert client.llm_secondary is not None
    assert client.llm_secondary.base_url == "http://127.0.0.1:8000/v1"
    client.close()


def test_local_llm_provider_is_authoritative(monkeypatch):
    """provider=local 时本地服务为主路径，且无云端降级（私有化数据不外发）。"""
    client, _ = _make_client(
        monkeypatch, llm_provider="local", local_llm_url="http://127.0.0.1:8000/v1"
    )

    assert client.llm_primary.base_url == "http://127.0.0.1:8000/v1"
    assert client.llm_primary.api_key is None
    assert client.llm_secondary is None
    client.close()


async def test_chat_local_provider_uses_local_model(monkeypatch):
    client, _ = _make_client(
        monkeypatch, llm_provider="local", local_llm_url="http://127.0.0.1:8000/v1"
    )
    fake_response = MagicMock()
    fake_response.json.return_value = {"choices": [{"message": {"content": "本地回答"}}]}
    fake_async = MagicMock()
    fake_async.post = AsyncMock(return_value=fake_response)
    fake_async.aclose = AsyncMock()
    monkeypatch.setattr(client.llm_primary, "_async_client", fake_async)

    result = await client.chat([{"role": "user", "content": "hi"}])

    assert result == "本地回答"
    payload = fake_async.post.call_args.kwargs["json"]
    assert payload["model"] == "Qwen/local-llm"
    await client.aclose()


def test_local_embedding_provider_uses_local_model_and_endpoint(monkeypatch):
    client, _ = _make_client(
        monkeypatch,
        embedding_provider="local",
        local_embedding_url="http://127.0.0.1:8000/v1",
    )

    assert client.embed_primary.base_url == "http://127.0.0.1:8000/v1"
    assert client.embed_secondary is None

    fake_response = MagicMock()
    fake_response.json.return_value = {"data": [{"embedding": [0.1, 0.2]}]}
    fake_sync = MagicMock()
    fake_sync.post.return_value = fake_response
    monkeypatch.setattr(client.embed_primary, "_sync_client", fake_sync)

    result = client.embed(["你好"])

    assert result == [[0.1, 0.2]]
    payload = fake_sync.post.call_args.kwargs["json"]
    assert payload["model"] == "BAAI/bge-m3"
    client.close()


def test_embed_falls_back_to_secondary_in_dashscope_mode(monkeypatch):
    """云端模式下 Embedding 主路径失败时降级本地端点。"""
    client, _ = _make_client(monkeypatch, local_embedding_url="http://127.0.0.1:8000/v1")

    bad_response = MagicMock()
    bad_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "boom", request=MagicMock(), response=MagicMock(text="bad gateway")
    )
    failing_sync = MagicMock()
    failing_sync.post.return_value = bad_response
    monkeypatch.setattr(client.embed_primary, "_sync_client", failing_sync)

    ok_response = MagicMock()
    ok_response.json.return_value = {"data": [{"embedding": [0.3, 0.4]}]}
    ok_sync = MagicMock()
    ok_sync.post.return_value = ok_response
    monkeypatch.setattr(client.embed_secondary, "_sync_client", ok_sync)

    result = client.embed(["你好"])

    assert result == [[0.3, 0.4]]
    assert ok_sync.post.call_args.kwargs["json"]["model"] == "BAAI/bge-m3"
    client.close()
