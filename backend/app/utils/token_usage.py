"""Token 用量统计工具。

使用 tiktoken 进行近似计数，主要用于生成阶段的用量统计与日志。
"""

from __future__ import annotations

import structlog
import tiktoken

logger = structlog.get_logger()


def _get_encoder(model: str = "cl100k_base") -> tiktoken.Encoding:
    """获取 tiktoken 编码器，失败时回退到 cl100k_base。"""
    try:
        return tiktoken.get_encoding(model)
    except Exception:
        logger.warning("token_encoding_fallback", requested=model, fallback="cl100k_base")
        return tiktoken.get_encoding("cl100k_base")


_ENCODER = _get_encoder("cl100k_base")


def count_tokens(text: str | None) -> int:
    """计算单段文本的 token 数量。"""
    if not text:
        return 0
    try:
        return len(_ENCODER.encode(text))
    except Exception:
        return 0


def count_messages_tokens(messages: list[dict]) -> int:
    """按 OpenAI 消息格式估算 prompt token 数量。

    规则参考 OpenAI cookbook：每条消息额外 3 个 token（role/content 分隔），
    最后追加 3 个 assistant priming token。
    """
    if not messages:
        return 0

    tokens_per_message = 3
    tokens_per_name = 1
    total = 0

    for message in messages:
        total += tokens_per_message
        for key, value in message.items():
            if value is None:
                continue
            total += count_tokens(str(value))
            if key == "name":
                total += tokens_per_name

    total += 3
    return total
