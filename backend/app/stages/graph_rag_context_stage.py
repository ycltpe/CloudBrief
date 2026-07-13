from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any

import structlog

from app.models.graph_schemas import KbGraphSchema, SubgraphContext

if TYPE_CHECKING:
    from app.clients.model_client import ModelClient
    from app.stores.graph_store import GraphStore

logger = structlog.get_logger()

_ENTITY_LINK_PROMPT = """请从用户问题中识别出可能对应知识图谱实体的名称。

要求：
1. 仅输出实体名称列表，不要解释。
2. 输出必须是合法的 JSON 数组，例如 ["张三", "CloudBrief"]。
3. 如果问题中没有明确实体，输出空数组 []。
4. 不要输出 markdown 代码块。"""


class GraphRAGContextStage:
    """在生成阶段注入图谱上下文。"""

    def __init__(
        self,
        graph_store: GraphStore,
        model_client: ModelClient | None = None,
    ):
        self.graph_store = graph_store
        self.model_client = model_client

    async def run(
        self,
        question: str,
        kb_id: str,
        schema: KbGraphSchema | None = None,
        entity_names: list[str] | None = None,
        max_hops: int = 2,
        max_nodes: int = 20,
    ) -> SubgraphContext:
        """根据问题获取子图上下文；失败时返回空上下文。"""
        diagnostics: dict[str, Any] = {"kb_id": kb_id}
        try:
            if not self.graph_store or not self.graph_store.is_available:
                diagnostics["skipped"] = "graph_store_unavailable"
                return SubgraphContext(diagnostics=diagnostics)

            if schema and not schema.enabled:
                diagnostics["skipped"] = "graph_rag_disabled"
                return SubgraphContext(diagnostics=diagnostics)

            if schema and not (schema.entity_types or schema.relation_types):
                diagnostics["skipped"] = "schema_empty"
                return SubgraphContext(diagnostics=diagnostics)

            names = entity_names or await self._link_entities(question, schema)
            diagnostics["linked_entities"] = names

            if not names:
                diagnostics["skipped"] = "no_linked_entities"
                return SubgraphContext(diagnostics=diagnostics)

            context = await self.graph_store.get_subgraph_context(
                entity_names=names,
                kb_id=kb_id,
                schema=schema,
                max_hops=max_hops,
                max_nodes=max_nodes,
            )
            context.diagnostics.update(diagnostics)
            return context
        except Exception as exc:
            logger.warning("graph_rag_context_stage_failed", error=str(exc), kb_id=kb_id)
            diagnostics["skipped"] = "exception"
            diagnostics["error"] = str(exc)
            return SubgraphContext(diagnostics=diagnostics)

    async def _link_entities(
        self,
        question: str,
        schema: KbGraphSchema | None,
    ) -> list[str]:
        """使用 LLM 从问题中链接实体。"""
        if not self.model_client:
            return []

        schema_text = ""
        if schema:
            entity_names = ", ".join(et.name for et in schema.entity_types)
            relation_names = ", ".join(rt.name for rt in schema.relation_types)
            schema_text = f"知识库中的实体类型包括：{entity_names}；关系类型包括：{relation_names}。"

        response = await self.model_client.chat(
            messages=[
                {"role": "system", "content": _ENTITY_LINK_PROMPT},
                {
                    "role": "user",
                    "content": f"{schema_text}\n\n用户问题：{question}",
                },
            ],
            stream=False,
            temperature=0.1,
        )
        cleaned = _sanitize_json_output(response)
        try:
            data = json.loads(cleaned)
            if isinstance(data, list):
                return [str(x).strip() for x in data if x]
            if isinstance(data, dict) and "entities" in data:
                return [str(x).strip() for x in data["entities"] if x]
        except json.JSONDecodeError:
            pass
        # 兜底：按常见分隔符提取引号/书名号内容
        return _fallback_extract_names(response)


def _sanitize_json_output(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _fallback_extract_names(text: str) -> list[str]:
    """从文本中提取被引号、书名号包围的内容。"""
    matches = re.findall(r'["""]([^"""]+)["""]|[《<]([^》>]+)[》>]', text)
    names: list[str] = []
    for a, b in matches:
        name = a or b
        if name:
            names.append(name.strip())
    return list(set(names))
