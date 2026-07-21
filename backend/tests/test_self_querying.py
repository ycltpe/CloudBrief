"""SelfQueryingStage 单元测试：字段/运算符白名单、JSON 解析与安全降级。"""

import json
import re
from unittest.mock import AsyncMock

import pytest

from app.stages.self_querying import (
    SELF_QUERYING_ALLOWED_FIELDS,
    SELF_QUERYING_ALLOWED_OPERATORS,
    SelfQueryingInput,
    SelfQueryingStage,
)


@pytest.fixture
def stage():
    model_client = AsyncMock()
    return SelfQueryingStage(model_client)


class TestValidateFilter:
    """filter 字段与运算符白名单校验。"""

    @pytest.mark.parametrize(
        "filter_expr",
        [
            'source_type == "changelog"',
            'source_type == "changelog" AND updated_at >= "2026-01-01T00:00:00"',
            'updated_at >= "2026-01-01" OR source_id == "help_docs/export-guide.md"',
            'title != "" AND source_type == "faq"',
            '(source_type == "changelog") AND (updated_at >= "2026-01-01")',
        ],
    )
    def test_valid_filters_accepted(self, filter_expr):
        valid, dropped, error = SelfQueryingStage._validate_filter(filter_expr)
        assert valid is True
        assert dropped == []
        assert error is None

    def test_non_whitelist_field_recorded(self):
        valid, dropped, error = SelfQueryingStage._validate_filter(
            'tenant_id == "abc" AND source_type == "changelog"'
        )
        assert valid is False
        assert "tenant_id" in dropped
        assert "source_type" not in dropped
        assert "白名单外字段" in error

    def test_invalid_operator_rejected(self):
        valid, dropped, error = SelfQueryingStage._validate_filter(
            'source_type LIKE "changelog"'
        )
        assert valid is False
        assert "LIKE" in error

    def test_not_operator_rejected(self):
        valid, dropped, error = SelfQueryingStage._validate_filter(
            'NOT source_type == "changelog"'
        )
        assert valid is False
        assert "NOT" in error or "非法字符" in error

    def test_invalid_syntax_characters_rejected(self):
        valid, dropped, error = SelfQueryingStage._validate_filter(
            'source_type == "changelog" + updated_at >= "2026-01-01"'
        )
        assert valid is False
        assert "非法字符" in error or "未识别的 token" in error

    def test_allowed_operators_coverage(self):
        for op in SELF_QUERYING_ALLOWED_OPERATORS:
            expr = f'source_type {op} "x"'
            valid, _, _ = SelfQueryingStage._validate_filter(expr)
            assert valid is True, f"operator {op} should be allowed"

    def test_allowed_fields_coverage(self):
        for field in SELF_QUERYING_ALLOWED_FIELDS:
            expr = f'{field} == "x"'
            valid, _, _ = SelfQueryingStage._validate_filter(expr)
            assert valid is True, f"field {field} should be allowed"


class TestParseLLMOutput:
    """LLM 输出 JSON 解析。"""

    def test_parse_valid_json(self):
        raw = json.dumps(
            {
                "query": "导出说明",
                "filter": 'source_type == "changelog"',
                "reasoning": "r",
            },
            ensure_ascii=False,
        )
        output = SelfQueryingStage._parse_llm_output(raw, "fallback")
        assert output.query == "导出说明"
        assert output.filter == 'source_type == "changelog"'
        assert output.reasoning == "r"

    def test_parse_markdown_code_block(self):
        raw = '```json\n{"query": "q", "filter": null, "reasoning": "r"}\n```'
        output = SelfQueryingStage._parse_llm_output(raw, "fallback")
        assert output.query == "q"
        assert output.filter is None

    def test_parse_invalid_json_returns_fallback(self):
        output = SelfQueryingStage._parse_llm_output("not json", "fallback")
        assert output.query == "fallback"
        assert output.filter is None
        assert "JSON" in output.reasoning

    def test_parse_non_object_returns_fallback(self):
        output = SelfQueryingStage._parse_llm_output("123", "fallback")
        assert output.query == "fallback"
        assert output.filter is None


class TestExecute:
    """Stage 端到端行为。"""

    async def test_execute_returns_valid_filter(self, stage):
        stage.model_client.chat.return_value = json.dumps(
            {
                "query": "更新日志里关于导出的说明",
                "filter": 'source_type == "changelog" AND updated_at >= "2026-06-21T00:00:00"',
                "reasoning": "限制 changelog",
            },
            ensure_ascii=False,
        )

        output = await stage.execute(SelfQueryingInput(question="近30天更新日志里关于导出的说明"))

        assert output.query == "更新日志里关于导出的说明"
        assert output.filter == 'source_type == "changelog" AND updated_at >= "2026-06-21T00:00:00"'
        assert output.dropped_fields == []
        stage.model_client.chat.assert_awaited_once()

    async def test_execute_drops_non_whitelist_field(self, stage):
        stage.model_client.chat.return_value = json.dumps(
            {
                "query": "q",
                "filter": 'tenant_id == "abc" AND source_type == "changelog"',
                "reasoning": "r",
            },
            ensure_ascii=False,
        )

        output = await stage.execute(SelfQueryingInput(question="q"))

        assert output.filter is None
        assert "tenant_id" in output.dropped_fields
        assert "白名单外字段" in output.reasoning

    async def test_execute_returns_null_when_no_filter(self, stage):
        stage.model_client.chat.return_value = json.dumps(
            {"query": "q", "filter": None, "reasoning": "无约束"},
            ensure_ascii=False,
        )

        output = await stage.execute(SelfQueryingInput(question="q"))

        assert output.query == "q"
        assert output.filter is None
        assert output.dropped_fields == []

    async def test_execute_fallback_on_llm_error(self, stage):
        stage.model_client.chat.side_effect = RuntimeError("llm down")

        output = await stage.execute(SelfQueryingInput(question="q"))

        assert output.query == "q"
        assert output.filter is None
        assert "llm down" in output.reasoning

    async def test_prompt_contains_field_and_operator_whitelist(self, stage):
        stage.model_client.chat.return_value = json.dumps(
            {"query": "q", "filter": None, "reasoning": ""},
            ensure_ascii=False,
        )

        await stage.execute(SelfQueryingInput(question="q"))

        messages = stage.model_client.chat.call_args.args[0]
        system_prompt = messages[0]["content"]
        for field in SELF_QUERYING_ALLOWED_FIELDS:
            assert field in system_prompt
        for op in SELF_QUERYING_ALLOWED_OPERATORS:
            assert op in system_prompt
        assert "当前 UTC 时间" in system_prompt


class TestBuildMessages:
    """Prompt 构建细节。"""

    def test_prompt_has_current_timestamp(self):
        stage = SelfQueryingStage(AsyncMock())
        messages = stage._build_messages("q")
        prompt = messages[0]["content"]
        assert re.search(r"当前 UTC 时间: \d{4}-\d{2}-\d{2}T", prompt)
