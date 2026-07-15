from unittest.mock import MagicMock

from app.clients.model_client import ModelClient
from app.config import get_settings


def test_ocr_image_posts_multimodal_payload(monkeypatch):
    client = ModelClient(get_settings())
    fake_response = MagicMock()
    fake_response.json.return_value = {"choices": [{"message": {"content": "识别结果文字"}}]}
    fake_sync = MagicMock()
    fake_sync.post.return_value = fake_response
    monkeypatch.setattr(client.primary, "_sync_client", fake_sync)

    text = client.ocr_image(b"\x89PNG fake-bytes")

    assert text == "识别结果文字"
    call = fake_sync.post.call_args
    assert call.args[0] == "/chat/completions"
    payload = call.kwargs["json"]
    assert payload["model"] == client.settings.ocr_model
    assert payload["temperature"] == 0
    content = payload["messages"][0]["content"]
    assert content[0]["type"] == "image_url"
    assert content[0]["image_url"]["url"].startswith("data:image/png;base64,")
    assert content[1]["type"] == "text"
