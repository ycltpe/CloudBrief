from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class EntityType(BaseModel):
    """实体类型定义。"""

    name: str = Field(..., min_length=1, max_length=64)
    description: str | None = Field(None, max_length=500)
    examples: list[str] = Field(default_factory=list)


class RelationType(BaseModel):
    """关系类型定义。"""

    name: str = Field(..., min_length=1, max_length=64)
    description: str | None = Field(None, max_length=500)
    source_types: list[str] = Field(default_factory=list)
    target_types: list[str] = Field(default_factory=list)


class KbGraphSchema(BaseModel):
    """单个知识库的 GraphRAG schema。"""

    kb_id: str = Field(..., min_length=1)
    enabled: bool = False
    enabled_by_user: bool = False
    enabled_at: datetime | None = None
    shadow_mode: bool = False
    entity_types: list[EntityType] = Field(default_factory=list)
    relation_types: list[RelationType] = Field(default_factory=list)
    version: int = 1
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    # 构建监控字段
    last_build_at: datetime | None = None
    last_build_task_id: str | None = None
    last_build_entities: int | None = None
    last_build_relations: int | None = None
    last_build_error: str | None = None
    last_build_diagnostics: dict[str, Any] = Field(default_factory=dict)

    def entity_type_names(self) -> list[str]:
        return [et.name for et in self.entity_types]

    def relation_type_names(self) -> list[str]:
        return [rt.name for rt in self.relation_types]


class Entity(BaseModel):
    """抽取出的实体。"""

    entity_id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    type: str = Field(..., min_length=1)
    aliases: list[str] = Field(default_factory=list)
    properties: dict[str, Any] = Field(default_factory=dict)
    source_chunk_ids: list[str] = Field(default_factory=list)
    source_doc_ids: list[str] = Field(default_factory=list)

    def unique_key(self, kb_id: str) -> str:
        """返回在 kb 内的唯一键，用于去重。"""
        return f"{kb_id}::{self.type}::{self.name}"


class Relation(BaseModel):
    """抽取出的关系。"""

    source: str = Field(..., min_length=1)
    target: str = Field(..., min_length=1)
    type: str = Field(..., min_length=1)
    properties: dict[str, Any] = Field(default_factory=dict)
    source_chunk_ids: list[str] = Field(default_factory=list)
    source_doc_ids: list[str] = Field(default_factory=list)

    def unique_key(self, kb_id: str) -> str:
        """返回在 kb 内的唯一键，用于去重。"""
        return f"{kb_id}::{self.source}::{self.type}::{self.target}"


class GraphExtractionResult(BaseModel):
    """一次抽取的完整输出。"""

    entities: list[Entity] = Field(default_factory=list)
    relations: list[Relation] = Field(default_factory=list)
    diagnostics: dict[str, Any] = Field(default_factory=dict)


class SubgraphContext(BaseModel):
    """子图上下文，用于注入生成阶段 prompt。"""

    entities: list[Entity] = Field(default_factory=list)
    relations: list[Relation] = Field(default_factory=list)
    text: str = ""
    diagnostics: dict[str, Any] = Field(default_factory=dict)
