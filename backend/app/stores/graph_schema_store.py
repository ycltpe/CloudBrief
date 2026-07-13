import json
from datetime import datetime

from app.models.graph_schemas import EntityType, KbGraphSchema, RelationType
from app.stores.db import KbGraphSchema as KbGraphSchemaRow
from app.stores.db import get_session_factory


class GraphSchemaStore:
    """知识库 GraphRAG schema 持久化仓库。"""

    def __init__(self, session_factory=None):
        self._session_factory = session_factory or get_session_factory()

    def get_by_directory_id(self, directory_id: int) -> KbGraphSchema | None:
        with self._session_factory() as session:
            row = session.query(KbGraphSchemaRow).filter_by(directory_id=directory_id).first()
            if not row:
                return None
            return self._row_to_model(row)

    def create_default(
        self,
        directory_id: int,
        enabled_by_user: bool = False,
    ) -> KbGraphSchema:
        with self._session_factory() as session:
            existing = session.query(KbGraphSchemaRow).filter_by(directory_id=directory_id).first()
            if existing:
                return self._row_to_model(existing)
            row = KbGraphSchemaRow(
                directory_id=directory_id,
                enabled=False,
                enabled_by_user=enabled_by_user,
                enabled_at=None,
                shadow_mode=False,
                entity_types_json="[]",
                relation_types_json="[]",
                version=1,
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            return self._row_to_model(row)

    def update_schema(
        self,
        directory_id: int,
        *,
        enabled: bool | None = None,
        enabled_by_user: bool | None = None,
        shadow_mode: bool | None = None,
        entity_types: list[EntityType] | None = None,
        relation_types: list[RelationType] | None = None,
    ) -> KbGraphSchema:
        with self._session_factory() as session:
            row = session.query(KbGraphSchemaRow).filter_by(directory_id=directory_id).first()
            if not row:
                raise ValueError("GRAPH_SCHEMA_NOT_FOUND")

            if enabled is not None:
                row.enabled = enabled
                row.enabled_at = datetime.utcnow() if enabled else row.enabled_at
            if enabled_by_user is not None:
                row.enabled_by_user = enabled_by_user
            if shadow_mode is not None:
                row.shadow_mode = shadow_mode
            if entity_types is not None:
                row.entity_types_json = json.dumps(
                    [et.model_dump() for et in entity_types], ensure_ascii=False
                )
            if relation_types is not None:
                row.relation_types_json = json.dumps(
                    [rt.model_dump() for rt in relation_types], ensure_ascii=False
                )

            row.version += 1
            row.updated_at = datetime.utcnow()
            session.commit()
            session.refresh(row)
            return self._row_to_model(row)

    def record_build(
        self,
        directory_id: int,
        task_id: str | None = None,
        entities: int | None = None,
        relations: int | None = None,
        error: str | None = None,
        diagnostics: dict | None = None,
    ) -> KbGraphSchema:
        """记录最近一次图索引构建结果，用于新鲜度与质量监控。"""
        with self._session_factory() as session:
            row = session.query(KbGraphSchemaRow).filter_by(directory_id=directory_id).first()
            if not row:
                raise ValueError("GRAPH_SCHEMA_NOT_FOUND")

            row.last_build_at = datetime.utcnow()
            row.last_build_task_id = task_id
            row.last_build_entities = entities
            row.last_build_relations = relations
            row.last_build_error = error
            row.last_build_diagnostics_json = json.dumps(diagnostics or {}, ensure_ascii=False)
            row.updated_at = datetime.utcnow()
            session.commit()
            session.refresh(row)
            return self._row_to_model(row)

    def set_enabled(self, directory_id: int, enabled: bool) -> KbGraphSchema:
        return self.update_schema(directory_id, enabled=enabled)

    @staticmethod
    def _row_to_model(row: KbGraphSchemaRow) -> KbGraphSchema:
        return KbGraphSchema(
            kb_id=str(row.directory_id),
            enabled=row.enabled,
            enabled_by_user=row.enabled_by_user,
            enabled_at=row.enabled_at,
            shadow_mode=row.shadow_mode,
            entity_types=[EntityType(**et) for et in json.loads(row.entity_types_json)],
            relation_types=[RelationType(**rt) for rt in json.loads(row.relation_types_json)],
            version=row.version,
            created_at=row.created_at,
            updated_at=row.updated_at,
            last_build_at=row.last_build_at,
            last_build_task_id=row.last_build_task_id,
            last_build_entities=row.last_build_entities,
            last_build_relations=row.last_build_relations,
            last_build_error=row.last_build_error,
            last_build_diagnostics=json.loads(row.last_build_diagnostics_json or "{}"),
        )
