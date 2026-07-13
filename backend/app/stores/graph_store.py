from __future__ import annotations

import json
import time
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

import structlog

from app.config import get_settings

if TYPE_CHECKING:
    from neo4j import AsyncDriver

logger = structlog.get_logger()

try:
    from neo4j import AsyncGraphDatabase

    _NEO4J_AVAILABLE = True
except ImportError:
    _NEO4J_AVAILABLE = False
    AsyncGraphDatabase = None  # type: ignore[misc, assignment]

from app.models.graph_schemas import (  # noqa: E402
    Entity,
    KbGraphSchema,
    Relation,
    SubgraphContext,
)


class GraphStoreError(Exception):
    """GraphStore 操作异常。"""


class GraphStore:
    """Neo4j 图存储封装，按 kb_id 隔离所有节点与关系。"""

    def __init__(self, driver: AsyncDriver | None = None):
        self._driver = driver
        self._closed = False

    @classmethod
    async def create(cls) -> GraphStore:
        """基于 .env 配置创建并返回已连接 store；Neo4j 未安装或连接失败时返回 None 驱动的 store。"""
        if not _NEO4J_AVAILABLE:
            logger.warning("neo4j_driver_unavailable", reason="optional_dependency_not_installed")
            return cls(driver=None)

        settings = get_settings()
        try:
            driver = AsyncGraphDatabase.driver(
                settings.neo4j_uri,
                auth=(settings.neo4j_user, settings.neo4j_password),
            )
            await driver.verify_connectivity()
            logger.info("neo4j_driver_connected", uri=settings.neo4j_uri)
            return cls(driver=driver)
        except Exception as exc:
            logger.warning("neo4j_driver_failed", error=str(exc))
            return cls(driver=None)

    async def initialize_schema(self) -> None:
        """创建唯一约束与索引；幂等。"""
        if not self._driver:
            return
        async with self._driver.session() as session:
            await session.run(
                "CREATE CONSTRAINT entity_unique IF NOT EXISTS "
                "FOR (e:Entity) REQUIRE (e.kb_id, e.type, e.name) IS UNIQUE"
            )
            await session.run(
                "CREATE INDEX entity_name_idx IF NOT EXISTS "
                "FOR (e:Entity) ON (e.kb_id, e.name)"
            )
            await session.run(
                "CREATE INDEX entity_alias_idx IF NOT EXISTS "
                "FOR (e:Entity) ON (e.aliases)"
            )
        logger.info("neo4j_schema_initialized")

    async def upsert_entities(self, entities: list[Entity], kb_id: str) -> int:
        """批量 upsert 实体，返回写入数量。"""
        if not self._driver:
            raise GraphStoreError("Neo4j driver is not available")
        if not entities:
            return 0

        async with self._timed_operation("upsert_entities", kb_id):
            written = 0
            async with self._driver.session() as session:
                for entity in entities:
                    await session.run(
                        """
                        MERGE (e:Entity {kb_id: $kb_id, type: $type, name: $name})
                        SET e.aliases = $aliases,
                            e.properties_json = $properties_json,
                            e.source_chunk_ids = $source_chunk_ids,
                            e.source_doc_ids = $source_doc_ids,
                            e.updated_at = datetime()
                        RETURN e.name AS name
                        """,
                        {
                            "kb_id": kb_id,
                            "type": entity.type,
                            "name": entity.name,
                            "aliases": list(set(entity.aliases or [])),
                            "properties_json": json.dumps(entity.properties or {}, ensure_ascii=False),
                            "source_chunk_ids": list(set(entity.source_chunk_ids or [])),
                            "source_doc_ids": list(set(entity.source_doc_ids or [])),
                        },
                    )
                    written += 1
        return written

    async def upsert_relations(self, relations: list[Relation], kb_id: str) -> int:
        """批量 upsert 关系，返回写入数量。"""
        if not self._driver:
            raise GraphStoreError("Neo4j driver is not available")
        if not relations:
            return 0

        async with self._timed_operation("upsert_relations", kb_id):
            written = 0
            async with self._driver.session() as session:
                for relation in relations:
                    await session.run(
                        """
                        MATCH (s:Entity {kb_id: $kb_id, name: $source}), (t:Entity {kb_id: $kb_id, name: $target})
                        MERGE (s)-[r:RELATION {type: $type}]->(t)
                        SET r.kb_id = $kb_id,
                            r.properties_json = $properties_json,
                            r.source_chunk_ids = $source_chunk_ids,
                            r.source_doc_ids = $source_doc_ids,
                            r.updated_at = datetime()
                        RETURN r.type AS type
                        """,
                        {
                            "kb_id": kb_id,
                            "source": relation.source,
                            "target": relation.target,
                            "type": relation.type,
                            "properties_json": json.dumps(relation.properties or {}, ensure_ascii=False),
                            "source_chunk_ids": list(set(relation.source_chunk_ids or [])),
                            "source_doc_ids": list(set(relation.source_doc_ids or [])),
                        },
                    )
                    written += 1
        return written

    async def get_subgraph_context(
        self,
        entity_names: list[str],
        kb_id: str,
        schema: KbGraphSchema | None = None,
        max_hops: int = 2,
        max_nodes: int = 20,
    ) -> SubgraphContext:
        """根据候选实体名查询 1-max_hops 子图。"""
        if not self._driver:
            return SubgraphContext(diagnostics={"skipped": "driver_unavailable"})
        if not entity_names:
            return SubgraphContext(diagnostics={"skipped": "no_entities"})

        rel_types = schema.relation_type_names() if schema else []
        node_rel_filter = "AND ALL(rel IN relationships(path) WHERE rel.type IN $rel_types)" if rel_types else ""
        rel_rel_filter = "AND ALL(rel IN r WHERE rel.type IN $rel_types)" if rel_types else ""

        query = f"""
        MATCH (n:Entity {{kb_id: $kb_id}})
        WHERE n.name IN $names OR any(alias IN n.aliases WHERE alias IN $names)
        WITH n
        MATCH path = (n)-[r:RELATION*1..{max_hops}]-(m:Entity {{kb_id: $kb_id}})
        WHERE ALL(rel IN relationships(path) WHERE rel.kb_id = $kb_id) {node_rel_filter}
        WITH DISTINCT nodes(path) AS nodes, relationships(path) AS rels
        UNWIND nodes AS node
        RETURN DISTINCT node.kb_id AS kb_id,
               node.name AS name,
               node.type AS type,
               node.aliases AS aliases,
               node.properties_json AS properties,
               node.source_chunk_ids AS source_chunk_ids,
               node.source_doc_ids AS source_doc_ids
        LIMIT $max_nodes
        """

        entities: list[Entity] = []
        relations: list[Relation] = []
        diagnostics: dict[str, Any] = {
            "input_entity_names": entity_names,
            "max_hops": max_hops,
        }

        async with self._timed_operation("get_subgraph_context", kb_id):
            async with self._driver.session() as session:
                node_result = await session.run(
                    query,
                    {
                        "kb_id": kb_id,
                        "names": list(set(entity_names)),
                        "rel_types": rel_types if rel_types else None,
                        "max_nodes": max_nodes,
                    },
                )
                async for record in node_result:
                    prop_json = record["properties"]
                    if isinstance(prop_json, str):
                        try:
                            props = json.loads(prop_json)
                        except Exception:
                            props = {}
                    else:
                        props = {}
                    entities.append(
                        Entity(
                            entity_id=f"{record['kb_id']}::{record['type']}::{record['name']}",
                            name=record["name"],
                            type=record["type"],
                            aliases=list(record["aliases"] or []),
                            properties=props,
                            source_chunk_ids=list(record["source_chunk_ids"] or []),
                            source_doc_ids=list(record["source_doc_ids"] or []),
                        )
                    )

                rel_result = await session.run(
                    f"""
                    MATCH (n:Entity {{kb_id: $kb_id}})
                    WHERE n.name IN $names OR any(alias IN n.aliases WHERE alias IN $names)
                    WITH n
                    MATCH (n)-[r:RELATION*1..{max_hops}]-(m:Entity {{kb_id: $kb_id}})
                    WHERE ALL(rel IN r WHERE rel.kb_id = $kb_id) {rel_rel_filter}
                    WITH DISTINCT r AS rels
                    UNWIND rels AS r
                    RETURN DISTINCT startNode(r).name AS source,
                                    endNode(r).name AS target,
                                    r.type AS type,
                                    r.properties_json AS properties,
                                    r.source_chunk_ids AS source_chunk_ids,
                                    r.source_doc_ids AS source_doc_ids
                    """,
                    {
                        "kb_id": kb_id,
                        "names": list(set(entity_names)),
                        "rel_types": rel_types if rel_types else None,
                    },
                )
                async for record in rel_result:
                    prop_json = record["properties"]
                    if isinstance(prop_json, str):
                        try:
                            props = json.loads(prop_json)
                        except Exception:
                            props = {}
                    else:
                        props = {}
                    relations.append(
                        Relation(
                            source=record["source"],
                            target=record["target"],
                            type=record["type"],
                            properties=props,
                            source_chunk_ids=list(record["source_chunk_ids"] or []),
                            source_doc_ids=list(record["source_doc_ids"] or []),
                        )
                    )

        diagnostics.update({
            "returned_entities": len(entities),
            "returned_relations": len(relations),
        })

        text = self._format_subgraph(entities, relations)
        return SubgraphContext(
            entities=entities,
            relations=relations,
            text=text,
            diagnostics=diagnostics,
        )

    def _format_subgraph(self, entities: list[Entity], relations: list[Relation]) -> str:
        if not entities:
            return ""
        entity_lines = [f"- [{e.type}] {e.name}" for e in entities]
        relation_lines = [f"- ({r.source}) --[{r.type}]--> ({r.target})" for r in relations]
        parts = ["图谱上下文："]
        parts.append("实体：")
        parts.extend(entity_lines)
        if relation_lines:
            parts.append("关系：")
            parts.extend(relation_lines)
        return "\n".join(parts)

    async def clear_kb(self, kb_id: str) -> None:
        """删除某知识库的全部图数据。"""
        if not self._driver:
            return
        async with self._timed_operation("clear_kb", kb_id):
            async with self._driver.session() as session:
                await session.run(
                    """
                    MATCH (n:Entity {kb_id: $kb_id})
                    OPTIONAL MATCH (n)-[r:RELATION]-()
                    DELETE r, n
                    """,
                    {"kb_id": kb_id},
                )
        logger.info("neo4j_kb_cleared", kb_id=kb_id)

    async def delete_entities_and_relations_by_doc(self, kb_id: str, doc_id: str) -> dict[str, int]:
        """按 doc_id 删除/清理图数据，用于单文件增量更新。

        策略：
        1. 删除仅由该 doc 支撑的关系；对还涉及其他 doc 的关系，从 source_doc_ids/source_chunk_ids 中移除该 doc。
        2. 删除仅由该 doc 支撑的实体（及其关系）；对还涉及其他 doc 的实体，从 source_doc_ids/source_chunk_ids 中移除该 doc。
        """
        if not self._driver:
            raise GraphStoreError("Neo4j driver is not available")
        if not doc_id:
            return {"deleted_relations": 0, "updated_relations": 0, "deleted_entities": 0, "updated_entities": 0}

        doc_id_prefix = f"{doc_id}:"

        async with self._timed_operation("delete_entities_and_relations_by_doc", kb_id):
            async with self._driver.session() as session:
                # 1. 删除仅来自该 doc 的关系
                rel_delete_result = await session.run(
                    """
                    MATCH (s:Entity {kb_id: $kb_id})-[r:RELATION]->(t:Entity {kb_id: $kb_id})
                    WHERE $doc_id IN r.source_doc_ids AND size(r.source_doc_ids) = 1
                    DELETE r
                    RETURN count(r) AS deleted_relations
                    """,
                    {"kb_id": kb_id, "doc_id": doc_id},
                )
                deleted_relations = 0
                async for record in rel_delete_result:
                    deleted_relations = record["deleted_relations"]

                # 2. 更新还来自其他 doc 的关系
                rel_update_result = await session.run(
                    """
                    MATCH (s:Entity {kb_id: $kb_id})-[r:RELATION]->(t:Entity {kb_id: $kb_id})
                    WHERE $doc_id IN r.source_doc_ids AND size(r.source_doc_ids) > 1
                    SET r.source_doc_ids = [x IN r.source_doc_ids WHERE x <> $doc_id],
                        r.source_chunk_ids = [x IN r.source_chunk_ids WHERE NOT x STARTS WITH $doc_id_prefix]
                    RETURN count(r) AS updated_relations
                    """,
                    {"kb_id": kb_id, "doc_id": doc_id, "doc_id_prefix": doc_id_prefix},
                )
                updated_relations = 0
                async for record in rel_update_result:
                    updated_relations = record["updated_relations"]

                # 3. 删除仅来自该 doc 的实体（连带其关系）
                entity_delete_result = await session.run(
                    """
                    MATCH (n:Entity {kb_id: $kb_id})
                    WHERE $doc_id IN n.source_doc_ids AND size(n.source_doc_ids) = 1
                    OPTIONAL MATCH (n)-[r:RELATION]-()
                    DELETE r, n
                    RETURN count(n) AS deleted_entities
                    """,
                    {"kb_id": kb_id, "doc_id": doc_id},
                )
                deleted_entities = 0
                async for record in entity_delete_result:
                    deleted_entities = record["deleted_entities"]

                # 4. 更新还来自其他 doc 的实体
                entity_update_result = await session.run(
                    """
                    MATCH (n:Entity {kb_id: $kb_id})
                    WHERE $doc_id IN n.source_doc_ids AND size(n.source_doc_ids) > 1
                    SET n.source_doc_ids = [x IN n.source_doc_ids WHERE x <> $doc_id],
                        n.source_chunk_ids = [x IN n.source_chunk_ids WHERE NOT x STARTS WITH $doc_id_prefix]
                    RETURN count(n) AS updated_entities
                    """,
                    {"kb_id": kb_id, "doc_id": doc_id, "doc_id_prefix": doc_id_prefix},
                )
                updated_entities = 0
                async for record in entity_update_result:
                    updated_entities = record["updated_entities"]

        logger.info(
            "neo4j_doc_deleted",
            kb_id=kb_id,
            doc_id=doc_id,
            deleted_relations=deleted_relations,
            updated_relations=updated_relations,
            deleted_entities=deleted_entities,
            updated_entities=updated_entities,
        )
        return {
            "deleted_relations": deleted_relations,
            "updated_relations": updated_relations,
            "deleted_entities": deleted_entities,
            "updated_entities": updated_entities,
        }

    async def close(self) -> None:
        if self._driver and not self._closed:
            await self._driver.close()
            self._closed = True
            logger.info("neo4j_driver_closed")

    @property
    def is_available(self) -> bool:
        return self._driver is not None and not self._closed

    @asynccontextmanager
    async def _timed_operation(self, operation: str, kb_id: str):
        """记录 Neo4j 查询耗时并输出结构化日志；慢查询输出 WARN。"""
        from app.services.settings_service import SettingsService

        threshold = SettingsService().get_runtime_value("graphrag_slow_query_threshold_ms")
        start = time.perf_counter()
        try:
            yield
        finally:
            duration_ms = (time.perf_counter() - start) * 1000
            is_slow = duration_ms > threshold
            log_level = logger.warning if is_slow else logger.info
            log_level(
                "neo4j_query_timed",
                operation=operation,
                kb_id=kb_id,
                duration_ms=round(duration_ms, 2),
                slow=is_slow,
                threshold_ms=threshold,
            )
