# 技术栈选型

本文件记录 GraphRAG 模块的推荐技术栈与备选方案。

## 后端技术栈

| 组件 | 推荐选型 | 说明 |
|---|---|---|
| 图数据库 | **Neo4j 5 Community** | 生态成熟，Cypher 易学，Docker Compose 一键部署，与 CloudBrief 现有部署模型一致。 |
| Python 驱动 | **neo4j-python-driver (async)** | 官方异步驱动，与 FastAPI lifespan 配合管理连接生命周期。 |
| 实体/关系抽取 | **LLM prompt + spaCy 混合** | PoC 以 LLM 为主验证效果；生产阶段引入 spaCy 依赖解析降低成本。 |
| Schema 定义 | **Pydantic + JSON Schema** | 知识库级实体/关系类型定义，存储于 MySQL `kb_graph_schemas` 表。 |
| 异步任务 | **Celery + Redis** | 复用现有基础设施；图谱构建任务路由到 `kb.index.rebuild` 队列。 |
| 事件流 | **Redis Pub/Sub + SSE** | 复用现有 `/index/tasks/{task_id}/events` 端点。 |

## 前端技术栈

| 组件 | 说明 |
|---|---|
| Next.js 14 + Tailwind CSS | 复用现有管理后台技术栈。 |
| `useTaskStream` hook | 扩展以识别 graph 相关 stage。 |
| shadcn/ui 表单组件 | 用于 schema 编辑器（JSON/表格式）。 |

## 部署增量

- `docker-compose.yml` 新增 `neo4j:5-community` 服务，暴露 Bolt `7687` 与 Browser `7474`。
- `.env` 新增 `NEO4J_URI`、`NEO4J_USER`、`NEO4J_PASSWORD`。
- 数据卷：`neo4j_data`、`neo4j_logs`。

## 可选依赖

```toml
[project.optional-dependencies]
graphrag = [
    "neo4j>=5.20",
]
```

## 备选方案

| 组件 | 备选 | 切换条件 |
|---|---|---|
| Neo4j | Memgraph | Cypher 兼容，迁移成本低；当 Neo4j 授权或成本成为瓶颈时评估。 |
| LLM 抽取 | spaCy 为主 + LLM 后处理 | 当 LLM token 成本过高且 schema 稳定时切换。 |
| 图实例隔离 | 独立 Neo4j database | 多租户或强合规要求时考虑。 |
