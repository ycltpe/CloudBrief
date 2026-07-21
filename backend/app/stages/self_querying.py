"""Self-Querying 白名单版：把自然语言约束翻译为 Milvus 标量过滤表达式。"""

import json
import re
from datetime import datetime, timedelta

from pydantic import BaseModel, Field

from app.clients.model_client import ModelClient
from app.services.settings_service import SettingsService
from app.stores.milvus import FILTER_FIELD_WHITELIST

# Self-Querying 允许输出的标量字段（与 Milvus 检索过滤白名单保持一致）
SELF_QUERYING_ALLOWED_FIELDS = FILTER_FIELD_WHITELIST

# Self-Querying 允许使用的比较/逻辑运算符
SELF_QUERYING_ALLOWED_OPERATORS = {"==", "!=", ">", "<", ">=", "<="}

_SELF_QUERYING_STRING_RE = re.compile(
    r'"[^"\\]*(?:\\.[^"\\]*)*"|\'[^\'\\]*(?:\\.[^\'\\]*)*\''
)
_SELF_QUERYING_TOKEN_RE = re.compile(
    r"\b(?:and|or)\b|[<>=!]+|\b[a-zA-Z_][a-zA-Z0-9_]*\b|\(|\)|\d+\.?\d*",
    re.IGNORECASE,
)


class SelfQueryingInput(BaseModel):
    question: str


class SelfQueryingOutput(BaseModel):
    query: str
    filter: str | None = None
    reasoning: str = ""
    dropped_fields: list[str] = Field(default_factory=list)


class SelfQueryingStage:
    """解析用户问题中的元数据约束，输出受控的 Milvus filter。

    - 仅允许使用白名单字段与运算符
    - 生成 filter 会再经过一次语法/字段白名单校验
    - 若 LLM 输出白名单外字段，直接丢弃该 filter 并记录 dropped_fields
    """

    def __init__(self, model_client: ModelClient):
        self.model_client = model_client
        self.settings_service = SettingsService()

    @property
    def name(self) -> str:
        return "self_querying"

    async def execute(self, input_data: SelfQueryingInput) -> SelfQueryingOutput:
        question = input_data.question.strip()
        if not question:
            return SelfQueryingOutput(query=question)

        messages = self._build_messages(question)
        try:
            raw = await self.model_client.chat(messages, stream=False, temperature=0.0)
        except Exception as exc:
            return SelfQueryingOutput(
                query=question,
                reasoning=f"Self-Querying LLM 调用失败: {exc}",
            )

        parsed = self._parse_llm_output(raw, fallback_question=question)

        if not parsed.filter:
            return parsed

        valid, dropped_fields, error = self._validate_filter(parsed.filter)
        if not valid:
            return SelfQueryingOutput(
                query=parsed.query,
                filter=None,
                reasoning=f"{parsed.reasoning}；filter 校验失败: {error}".strip("；"),
                dropped_fields=dropped_fields,
            )

        return SelfQueryingOutput(
            query=parsed.query,
            filter=parsed.filter,
            reasoning=parsed.reasoning,
        )

    def _build_messages(self, question: str) -> list[dict[str, str]]:
        now = datetime.utcnow()
        thirty_days_ago = (now - timedelta(days=30)).isoformat()

        system_prompt = (
            "你是一个企业知识库查询约束解析器。请从用户问题中提取可在元数据上表达的过滤条件，"
            "并输出严格符合以下白名单的 Milvus 标量过滤表达式。\n\n"
            "允许使用的字段（仅限这些）: "
            + ", ".join(sorted(SELF_QUERYING_ALLOWED_FIELDS))
            + "\n"
            "允许使用的运算符（仅限这些）: "
            + ", ".join(sorted(SELF_QUERYING_ALLOWED_OPERATORS))
            + ", AND, OR\n"
            "时间字段 updated_at 使用 ISO 8601 字符串，例如 updated_at >= \"2026-04-22T00:00:00\"。\n"
            f"当前 UTC 时间: {now.isoformat()}\n\n"
            "输出必须是 JSON，且仅包含以下字段，不要 Markdown 代码块:\n"
            '{"query": "去除过滤条件后的检索问题", "filter": "Milvus filter 或 null", "reasoning": "提取理由"}\n\n'
            "示例:\n"
            f'用户: 近30天更新日志里关于导出的说明\n'
            f'输出: {{"query": "更新日志里关于导出的说明", '
            f'"filter": "source_type == \\"changelog\\" AND updated_at >= \\"{thirty_days_ago}\\"", '
            f'"reasoning": "限定来源类型为 changelog 且更新时间在30天内"}}\n\n'
            "如果问题中没有可提取的元数据约束，filter 必须设为 null。"
        )
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": question},
        ]

    @staticmethod
    def _parse_llm_output(raw: str, fallback_question: str) -> SelfQueryingOutput:
        if not raw:
            return SelfQueryingOutput(query=fallback_question)

        text = raw.strip()
        # 去除可能的 Markdown 代码块
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.MULTILINE).strip()

        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            return SelfQueryingOutput(
                query=fallback_question,
                reasoning=f"LLM 输出不是合法 JSON: {exc}",
            )

        if not isinstance(data, dict):
            return SelfQueryingOutput(
                query=fallback_question,
                reasoning="LLM 输出 JSON 不是对象",
            )

        query = data.get("query") or fallback_question
        filter_expr = data.get("filter")
        if filter_expr is not None and not isinstance(filter_expr, str):
            filter_expr = None
        reasoning = data.get("reasoning") or ""
        return SelfQueryingOutput(
            query=str(query).strip(),
            filter=filter_expr.strip() if filter_expr else None,
            reasoning=str(reasoning).strip(),
        )

    @staticmethod
    def _validate_filter(filter_expr: str) -> tuple[bool, list[str], str | None]:
        """校验 filter 的字段与运算符均在白名单内。

        返回 (是否有效, 被丢弃字段列表, 错误信息)。
        """
        if not filter_expr or not filter_expr.strip():
            return True, [], None

        cleaned = _SELF_QUERYING_STRING_RE.sub("", filter_expr)

        # 提取所有 token，未匹配到的剩余字符视为非法语法
        tokens: list[str] = _SELF_QUERYING_TOKEN_RE.findall(cleaned)
        matched_span_text = _SELF_QUERYING_TOKEN_RE.sub("", cleaned).strip()
        if matched_span_text:
            return False, [], f"包含非法字符或语法片段: {matched_span_text[:80]}"

        dropped_fields: list[str] = []
        for token in tokens:
            # 比较运算符
            if any(op in token for op in ("=", "<", ">", "!")):
                if token not in SELF_QUERYING_ALLOWED_OPERATORS:
                    return False, [], f"运算符 '{token}' 不在白名单内"
                continue

            # 标识符：字段名或 and/or
            if re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", token):
                lower = token.lower()
                if lower in {"and", "or"}:
                    continue
                if token in SELF_QUERYING_ALLOWED_FIELDS:
                    continue
                if token not in dropped_fields:
                    dropped_fields.append(token)
                continue

            # 括号与数字字面量允许
            if token in {"(", ")"} or re.match(r"^\d+\.?\d*$", token):
                continue

            return False, [], f"未识别的 token: {token}"

        if dropped_fields:
            return False, dropped_fields, f"包含白名单外字段: {', '.join(dropped_fields)}"

        return True, [], None
