"""GraphRAG 增量更新性能基准脚本。

用法：
    uv run python scripts/benchmark_graph_incremental.py --kb-id 1 --doc-id kb/dir_1/sample.md

说明：
- 该脚本先构造若干模拟实体/关系并全量写入 Neo4j，然后模拟"单文件更新"：
  删除指定 doc 相关的实体/关系，再写入新版本的实体/关系。
- 输出全量写入耗时、增量删除+写入耗时、以及两者比例。
- 若要测试完整端到端（含 LLM 抽取），请通过管理后台上传文件并观察 Celery 任务日志。
"""

import asyncio
import random
import string
import time
from argparse import ArgumentParser

from app.models.graph_schemas import Entity, Relation
from app.stores.graph_store import GraphStore


def _random_name(length: int = 8) -> str:
    return "".join(random.choices(string.ascii_lowercase, k=length))


def _make_entities(kb_id: str, doc_ids: list[str], entities_per_doc: int) -> list[Entity]:
    entities: list[Entity] = []
    for doc_id in doc_ids:
        for i in range(entities_per_doc):
            name = f"entity_{doc_id.replace('/', '_')}_{i}"
            entities.append(
                Entity(
                    entity_id=f"{kb_id}::测试实体::{name}",
                    name=name,
                    type="测试实体",
                    aliases=[],
                    properties={"idx": i},
                    source_chunk_ids=[f"{doc_id}:{i}"],
                    source_doc_ids=[doc_id],
                )
            )
    return entities


def _make_relations(entities: list[Entity]) -> list[Relation]:
    relations: list[Relation] = []
    # 每个 doc 内部形成链式关系
    by_doc: dict[str, list[Entity]] = {}
    for e in entities:
        doc_id = e.source_doc_ids[0]
        by_doc.setdefault(doc_id, []).append(e)
    for doc_entities in by_doc.values():
        for i in range(len(doc_entities) - 1):
            relations.append(
                Relation(
                    source=doc_entities[i].name,
                    target=doc_entities[i + 1].name,
                    type="关联",
                    properties={},
                    source_chunk_ids=doc_entities[i].source_chunk_ids,
                    source_doc_ids=doc_entities[i].source_doc_ids,
                )
            )
    return relations


async def benchmark(kb_id: str, target_doc_id: str, doc_count: int = 10, entities_per_doc: int = 50):
    store = await GraphStore.create()
    if not store.is_available:
        raise RuntimeError("Neo4j 不可用，请检查 NEO4J_URI/NEO4J_USER/NEO4J_PASSWORD")

    await store.initialize_schema()

    # 清理该 KB 旧数据
    await store.clear_kb(kb_id)

    doc_ids = [f"kb/dir_{kb_id}/doc_{i}.md" for i in range(doc_count)]
    all_entities = _make_entities(kb_id, doc_ids, entities_per_doc)
    all_relations = _make_relations(all_entities)

    print(f"准备数据：{len(doc_ids)} 个 doc，{len(all_entities)} 个实体，{len(all_relations)} 个关系")

    # 1. 全量写入
    start = time.perf_counter()
    await store.upsert_entities(all_entities, kb_id)
    await store.upsert_relations(all_relations, kb_id)
    full_duration = time.perf_counter() - start
    print(f"全量写入耗时：{full_duration:.3f}s")

    # 2. 模拟增量更新：删除 target_doc 并重新写入同 doc 的新数据
    new_entities = _make_entities(kb_id, [target_doc_id], entities_per_doc)
    new_relations = _make_relations(new_entities)

    start = time.perf_counter()
    await store.delete_entities_and_relations_by_doc(kb_id, target_doc_id)
    await store.upsert_entities(new_entities, kb_id)
    await store.upsert_relations(new_relations, kb_id)
    incremental_duration = time.perf_counter() - start
    print(f"增量更新耗时：{incremental_duration:.3f}s")

    ratio = incremental_duration / full_duration if full_duration > 0 else 0
    print(f"增量/全量比例：{ratio:.2%}")

    if ratio <= 0.20:
        print("✅ 满足增量更新时间 ≤ 全量重建 20% 的目标")
    else:
        print("⚠️  增量更新时间超过全量重建 20%，建议优化")

    await store.close()


if __name__ == "__main__":
    parser = ArgumentParser(description="GraphRAG 增量更新性能基准")
    parser.add_argument("--kb-id", default="1", help="知识库 ID")
    parser.add_argument("--doc-id", default="kb/dir_1/doc_0.md", help="要模拟更新的 doc_id")
    parser.add_argument("--doc-count", type=int, default=10, help="模拟 doc 数量")
    parser.add_argument("--entities-per-doc", type=int, default=50, help="每个 doc 的实体数")
    args = parser.parse_args()

    asyncio.run(
        benchmark(
            kb_id=args.kb_id,
            target_doc_id=args.doc_id,
            doc_count=args.doc_count,
            entities_per_doc=args.entities_per_doc,
        )
    )
