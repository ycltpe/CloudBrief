from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any

import structlog

from app.config import get_settings
from app.models.graph_schemas import (
    Entity,
    EntityType,
    GraphExtractionResult,
    KbGraphSchema,
    Relation,
    RelationType,
)
from app.services.settings_service import SettingsService

if TYPE_CHECKING:
    from app.clients.model_client import ModelClient

logger = structlog.get_logger()

_EXTRACTION_SYSTEM_PROMPT = """你是一名企业知识图谱抽取专家。请严格根据下面的 schema，从给定的文本片段中抽取实体和关系。

要求：
1. 仅抽取 schema 中定义的实体类型和关系类型。
2. 实体必须出现在文本中，禁止编造。
3. 关系必须能在文本中找到依据，禁止推断不存在的关系。
4. 输出必须是合法的 JSON，不要包含 markdown 代码块或其他说明文字。
5. 同一实体在不同 chunk 中重复出现时，只输出一次，合并 source_chunk_ids。
6. 实体名尽量使用文本中的标准称谓，可附加常见别名到 aliases。

输出格式：
{
  "entities": [
    {
      "name": "实体名称",
      "type": "实体类型",
      "aliases": ["别名1"],
      "properties": {"属性名": "属性值"},
      "source_chunk_ids": ["chunk_id_1"]
    }
  ],
  "relations": [
    {
      "source": "源实体名称",
      "target": "目标实体名称",
      "type": "关系类型",
      "properties": {"属性名": "属性值"},
      "source_chunk_ids": ["chunk_id_1"]
    }
  ]
}"""

_SCHEMA_RECOMMEND_SYSTEM_PROMPT = """你是一名企业知识 schema 设计专家。请阅读以下文本片段样本，推荐适合构建知识图谱的实体类型（entity_types）和关系类型（relation_types）。

要求：
1. 实体类型和关系类型应贴合文本内容，数量适中（实体类型 3-8 个，关系类型 3-8 个）。
2. 每个类型需包含名称、简短描述和示例。
3. 输出必须是合法的 JSON，不要包含 markdown 代码块或其他说明文字。

输出格式：
{
  "entity_types": [
    {"name": "人员", "description": "...", "examples": ["张三", "李四"]}
  ],
  "relation_types": [
    {"name": "汇报给", "description": "...", "source_types": ["人员"], "target_types": ["人员"]}
  ]
}"""


def _sanitize_json_output(text: str) -> str:
    """去除 markdown 代码块与首尾空白。"""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


class GraphExtractionService:
    """基于 LLM 从 chunks 抽取实体/关系，并支持 schema 自动推荐。"""

    def __init__(self, model_client: ModelClient):
        self.model_client = model_client
        self.settings = get_settings()
        self.settings_service = SettingsService()

    async def extract(
        self,
        chunks: list[Any],
        schema: KbGraphSchema | None = None,
        kb_id: str | None = None,
        batch_size: int = 3,
    ) -> GraphExtractionResult:
        """抽取实体与关系；按 batch_size 分批调用 LLM，避免单请求过大导致超时。

        chunks 可以是 app.stages.base.Chunk 或任何含 chunk_id/content/source_id 的对象。
        """
        if not chunks:
            return GraphExtractionResult()

        schema_text = self._schema_to_prompt(schema) if schema else "未提供 schema，请根据文本自行推断合适的实体/关系类型。"

        all_entities: list[Entity] = []
        all_relations: list[Relation] = []
        diagnostics: dict[str, Any] = {"batches": 0, "parse_errors": 0}

        for i in range(0, len(chunks), batch_size):
            batch = chunks[i : i + batch_size]
            user_prompt = self._build_extraction_prompt(batch, schema_text)
            response = await self.model_client.chat(
                messages=[
                    {"role": "system", "content": _EXTRACTION_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                stream=False,
                temperature=0.1,
                timeout=self.settings_service.get_runtime_value("graphrag_timeout_seconds"),
            )
            cleaned = _sanitize_json_output(response)
            diagnostics["batches"] += 1
            try:
                data = json.loads(cleaned)
            except json.JSONDecodeError as exc:
                logger.warning("graph_extraction_json_parse_failed", raw=cleaned[:500], error=str(exc))
                diagnostics["parse_errors"] += 1
                continue

            batch_entities = self._normalize_entities(data.get("entities", []), batch, kb_id)
            batch_relations = self._normalize_relations(data.get("relations", []), batch, kb_id)
            all_entities.extend(batch_entities)
            all_relations.extend(batch_relations)

        # 跨 batch 去重
        merged_entities = self._merge_entities(all_entities)
        merged_relations = self._merge_relations(all_relations)
        return GraphExtractionResult(
            entities=merged_entities,
            relations=merged_relations,
            diagnostics=diagnostics,
        )

    async def recommend_schema(
        self,
        chunks: list[Any],
        kb_id: str,
    ) -> KbGraphSchema:
        """基于 chunks 采样推荐 schema。"""
        sample_chunks = chunks[:10]  # 取前 10 个 chunk 作为样本
        sample_text = "\n\n---\n\n".join(
            f"[{getattr(c, 'chunk_id', '')}] {getattr(c, 'content', '')}" for c in sample_chunks
        )
        user_prompt = f"文本片段样本：\n\n{sample_text}"

        response = await self.model_client.chat(
            messages=[
                {"role": "system", "content": _SCHEMA_RECOMMEND_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            stream=False,
            temperature=0.3,
            timeout=self.settings_service.get_runtime_value("graphrag_timeout_seconds"),
        )

        cleaned = _sanitize_json_output(response)
        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            logger.warning("schema_recommend_json_parse_failed", raw=cleaned[:500], error=str(exc))
            return KbGraphSchema(kb_id=kb_id)

        entity_types = [
            EntityType(**et) for et in data.get("entity_types", [])
        ]
        relation_types = [
            RelationType(**rt) for rt in data.get("relation_types", [])
        ]
        return KbGraphSchema(
            kb_id=kb_id,
            entity_types=entity_types,
            relation_types=relation_types,
        )

    def _schema_to_prompt(self, schema: KbGraphSchema) -> str:
        lines = ["实体类型："]
        for et in schema.entity_types:
            lines.append(f"- {et.name}：{et.description or ''} 示例：{et.examples}")
        lines.append("关系类型：")
        for rt in schema.relation_types:
            lines.append(
                f"- {rt.name}：{rt.description or ''} "
                f"源实体：{rt.source_types} 目标实体：{rt.target_types}"
            )
        return "\n".join(lines)

    def _build_extraction_prompt(self, chunks: list[Any], schema_text: str) -> str:
        parts = [f"Schema 定义：\n{schema_text}\n\n文本片段："]
        for chunk in chunks:
            chunk_id = getattr(chunk, "chunk_id", "")
            content = getattr(chunk, "content", "")
            parts.append(f"[{chunk_id}]\n{content}")
        return "\n\n---\n\n".join(parts)

    def _normalize_entities(
        self,
        raw_entities: list[dict[str, Any]],
        chunks: list[Any],
        kb_id: str | None,
    ) -> list[Entity]:
        seen: set[str] = set()
        result: list[Entity] = []
        chunk_id_map = {getattr(c, "content", ""): getattr(c, "chunk_id", "") for c in chunks}
        for raw in raw_entities:
            name = str(raw.get("name", "")).strip()
            etype = str(raw.get("type", "")).strip()
            if not name or not etype:
                continue
            key = f"{etype}::{name}"
            if key in seen:
                continue
            seen.add(key)

            source_chunk_ids = self._extract_source_chunk_ids(raw, chunks, chunk_id_map)
            source_doc_ids = self._extract_source_doc_ids(raw, source_chunk_ids)
            result.append(
                Entity(
                    entity_id=f"{kb_id or ''}::{etype}::{name}",
                    name=name,
                    type=etype,
                    aliases=[str(a) for a in raw.get("aliases", []) if a],
                    properties=raw.get("properties", {}) or {},
                    source_chunk_ids=source_chunk_ids,
                    source_doc_ids=source_doc_ids,
                )
            )
        return result

    def _merge_entities(self, entities: list[Entity]) -> list[Entity]:
        merged: dict[str, Entity] = {}
        for e in entities:
            key = f"{e.type}::{e.name}"
            if key not in merged:
                merged[key] = e
                continue
            existing = merged[key]
            existing.aliases = list(set(existing.aliases + e.aliases))
            existing.source_chunk_ids = list(set(existing.source_chunk_ids + e.source_chunk_ids))
            existing.source_doc_ids = list(set(existing.source_doc_ids + e.source_doc_ids))
            existing.properties.update(e.properties)
        return list(merged.values())

    def _normalize_relations(
        self,
        raw_relations: list[dict[str, Any]],
        chunks: list[Any],
        kb_id: str | None,
    ) -> list[Relation]:
        seen: set[str] = set()
        result: list[Relation] = []
        chunk_id_map = {getattr(c, "content", ""): getattr(c, "chunk_id", "") for c in chunks}
        for raw in raw_relations:
            source = str(raw.get("source", "")).strip()
            target = str(raw.get("target", "")).strip()
            rel_type = str(raw.get("type", "")).strip()
            if not source or not target or not rel_type:
                continue
            key = f"{source}::{rel_type}::{target}"
            if key in seen:
                continue
            seen.add(key)

            source_chunk_ids = self._extract_source_chunk_ids(raw, chunks, chunk_id_map)
            source_doc_ids = self._extract_source_doc_ids(raw, source_chunk_ids)
            result.append(
                Relation(
                    source=source,
                    target=target,
                    type=rel_type,
                    properties=raw.get("properties", {}) or {},
                    source_chunk_ids=source_chunk_ids,
                    source_doc_ids=source_doc_ids,
                )
            )
        return result

    def _merge_relations(self, relations: list[Relation]) -> list[Relation]:
        merged: dict[str, Relation] = {}
        for r in relations:
            key = f"{r.source}::{r.type}::{r.target}"
            if key not in merged:
                merged[key] = r
                continue
            existing = merged[key]
            existing.source_chunk_ids = list(set(existing.source_chunk_ids + r.source_chunk_ids))
            existing.source_doc_ids = list(set(existing.source_doc_ids + r.source_doc_ids))
            existing.properties.update(r.properties)
        return list(merged.values())

    def _extract_source_chunk_ids(
        self,
        raw: dict[str, Any],
        chunks: list[Any],
        chunk_id_map: dict[str, str],
    ) -> list[str]:
        explicit = raw.get("source_chunk_ids", [])
        if explicit:
            return [str(x) for x in explicit if x]
        # 如果 LLM 未给出，尝试根据内容匹配（简单包含判断）
        text = json.dumps(raw, ensure_ascii=False)
        matched: list[str] = []
        for chunk in chunks:
            content = getattr(chunk, "content", "")
            chunk_id = getattr(chunk, "chunk_id", "")
            if content and any(sentence in content for sentence in text.split("。")):
                matched.append(chunk_id)
        return matched or [chunk_id_map.get(getattr(chunks[0], "content", ""), "")] if chunks else []

    def _extract_source_doc_ids(self, raw: dict[str, Any], source_chunk_ids: list[str]) -> list[str]:
        explicit = raw.get("source_doc_ids", [])
        if explicit:
            return [str(x) for x in explicit if x]
        # 从 chunk_id 推导 doc_id，约定 chunk_id 格式为 source_type:source_id:chunk_index
        doc_ids: list[str] = []
        for chunk_id in source_chunk_ids:
            parts = str(chunk_id).split(":")
            if len(parts) >= 3:
                doc_ids.append(f"{parts[0]}:{parts[1]}")
        return list(set(doc_ids))
