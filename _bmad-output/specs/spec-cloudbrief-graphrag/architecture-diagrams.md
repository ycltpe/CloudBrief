# 架构图

## 系统架构总览

```
┌─────────────────────────────────────────┐
│            FastAPI Application          │
│  ┌─────────┐ ┌─────────┐ ┌──────────┐  │
│  │ Chat API│ │Index API│ │Admin API │  │
│  └────┬────┘ └────┬────┘ └────┬─────┘  │
│       └─────────────┬──────────┘        │
│  ┌──────────────────┴─────────────────┐ │
│  │       ChatService / IndexService   │ │
│  └──────────────────┬─────────────────┘ │
│  ┌──────────────────┴─────────────────┐ │
│  │  RetrievalPipeline │ GenerationPipeline│
│  │  ├─ VectorStage    │ ├─ RefusalStage  │
│  │  ├─ BM25Stage      │ ├─ GraphRAGCtx   │◄── 新增
│  │  ├─ HybridFusion   │ ├─ LLMStage      │
│  │  └─ RerankStage    │ └─ CitationStage │
│  └─────────────────────────────────────┘ │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ │
│  │MilvusStore│ │ BM25Store│ │GraphStore│◄─┘ 新增
│  └──────────┘ └──────────┘ └──────────┘
└─────────────────────────────────────────┘
         │              │              │
    ┌────┴────┐    ┌────┴────┐   ┌────┴────┐
    │ Milvus  │    │  BM25   │   │  Neo4j  │   ◄── 新增
    └─────────┘    └─────────┘   └─────────┘
```

## 生成阶段增强流程

```
用户问题
   ↓
QueryRewriteStage（现有）
   ↓
RetrievalPipeline（现有，不变）
   ├─→ VectorRetrievalStage
   ├─→ BM25RetrievalStage
   ├─→ HybridFusionStage
   └─→ RerankingStage
   ↓
RetrievalResult（chunks + scores）
   ↓
GenerationPipeline
   ├─→ 硬分支拒答（现有）
   ├─→ GraphRAGContextStage（新增，仅当 kb.graph_rag_enabled=true）
   │      ├─→ 实体识别
   │      ├─→ 子图检索（1–2 跳）
   │      └─→ 文本化图谱上下文注入 prompt
   └─→ GenerationLLMStage（现有）
   ↓
CitationParserStage（现有）
   ↓
返回答案
```

## 图谱构建事件流

```
前端 ──POST /index/{kb_id}/rebuild-graph──→ FastAPI
                                          │
                                          ↓
                                      Celery Task
                                          │
                                          ↓
                              Redis Pub/Sub (index:tasks:{task_id})
                                          │
                                          ↓
前端 ←──────SSE /index/tasks/{task_id}/events───── FastAPI
```

## 模块边界

| 模块 | 职责 | 与现有系统关系 |
|---|---|---|
| `app/stores/graph_store.py` | Neo4j 访问抽象 | 与 `MilvusStore`、`BM25Store` 同级 |
| `app/services/graph_extraction.py` | 实体/关系抽取 | 被 `graph_indexing` 任务调用 |
| `app/stages/graph_rag_context_stage.py` | 生成阶段注入图谱上下文 | 被 `GenerationPipeline` 调用 |
| `app/tasks/graph_indexing.py` | Celery 图谱构建任务 | 与 `indexing.py` 同级 |
| `app/models/graph_schemas.py` | 实体/关系/schema Pydantic 模型 | 归入 `app/models/` |
