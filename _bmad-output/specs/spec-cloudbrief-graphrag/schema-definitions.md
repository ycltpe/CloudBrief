# 数据模型与 Schema 定义

## 图数据模型

所有节点与关系必须携带 `kb_id` 属性实现知识库级隔离。

```cypher
(:KbGraph {kb_id: "uuid", version: "v2", status: "active", updated_at: datetime()})

(:Entity {
    kb_id: "uuid",
    entity_id: "e1",
    type: "Person",
    name: "张三",
    attrs: { "职位": "技术总监" },
    chunk_ids: ["chunk-1", "chunk-2"],
    doc_ids: ["doc-1"]
})

(:Entity)-[:RELATES_TO {
    kb_id: "uuid",
    type: "任职于",
    attrs: { "since": "2020", "until": "2023" },
    chunk_ids: ["chunk-1"],
    doc_ids: ["doc-1"]
}]->(:Entity)
```

## 节点与关系约定

| 元素 | 必需属性 | 说明 |
|---|---|---|
| `Entity` | `kb_id`, `entity_id`, `type`, `name` | `entity_id` 在知识库内唯一；`name` 用于展示与查询匹配。 |
| `RELATES_TO` | `kb_id`, `type` | 关系类型存储在属性中，便于动态 schema。 |
| `KbGraph` | `kb_id`, `version`, `status` | 用于元数据管理与切换（可选，MVP 可不实现版本切换）。 |

## 推荐索引与约束

```cypher
CREATE CONSTRAINT entity_id_kb_id IF NOT EXISTS
FOR (e:Entity) REQUIRE (e.kb_id, e.entity_id) IS UNIQUE;

CREATE INDEX entity_name_kb_id IF NOT EXISTS
FOR (e:Entity) ON (e.kb_id, e.name);
```

## Pydantic Schema 定义

```python
from pydantic import BaseModel, Field

class EntityType(BaseModel):
    name: str = Field(..., description="实体类型名，如 Person")
    description: str = Field(..., description="类型说明，用于抽取 prompt")
    attributes: dict[str, str] = Field(default_factory=dict, description="属性名->类型")

class RelationType(BaseModel):
    name: str = Field(..., description="关系类型名，如 任职于")
    source_types: list[str] = Field(..., description="允许的源实体类型")
    target_types: list[str] = Field(..., description="允许的目标实体类型")
    attributes: dict[str, str] = Field(default_factory=dict, description="属性名->类型")

class KbGraphSchema(BaseModel):
    kb_id: str
    enabled: bool = False
    entity_types: list[EntityType] = Field(default_factory=list)
    relation_types: list[RelationType] = Field(default_factory=list)
    extraction_prompt: str | None = None
    max_hops: int = 1
```

## 数据库表扩展

### MySQL

```sql
CREATE TABLE kb_graph_schemas (
    kb_id VARCHAR(64) PRIMARY KEY,
    enabled BOOLEAN DEFAULT FALSE,
    schema_json JSON NOT NULL,
    extraction_prompt TEXT,
    max_hops INT DEFAULT 1,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

CREATE TABLE kb_graph_build_tasks (
    id VARCHAR(64) PRIMARY KEY,
    kb_id VARCHAR(64) NOT NULL,
    status VARCHAR(32) NOT NULL,
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP NULL,
    error_message TEXT
);
```

## 安全规则

- 所有 Cypher 查询必须参数化，禁止字符串拼接。
- `kb_id` 必须作为每个 `MATCH`/`MERGE` 查询的过滤条件。
- 管理接口 `PUT /admin/kbs/{kb_id}/graph-rag-config` 需 `admin` 角色。
