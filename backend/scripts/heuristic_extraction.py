"""启发式图抽取，用于 PoC 快速验证管线。"""
from __future__ import annotations

import re

from app.models.graph_schemas import Entity, GraphExtractionResult, Relation
from app.stages.base import Chunk


def _normalize_name(name: str) -> str:
    return name.strip().strip("，,、.。\n")


def extract(chunks: list[Chunk], kb_id: str) -> GraphExtractionResult:
    entities: dict[str, Entity] = {}
    relations: dict[str, Relation] = {}

    person_pattern = re.compile(r"([一-龥]{2,4})(?:\s*[:：]\s*|担任|任职于|加入|向)(?!\s*公司)")
    company_pattern = re.compile(r"([一-龥]{2,10}(?:科技|集团|软件|银行|制造|教育|网络|云|数据|中心|办公|智能|智算|国信|联创|未来|长江|华东|星辰|银河|磐石|百川|灵犀|明道|锐捷))")
    dept_pattern = re.compile(r"([一-龥]{2,10}(?:部|中心|组|团队|研发部|销售部|市场部|财务部|人力资源部|法务部|行政部|产品部|测试部|设计部|算法部|运营部))")

    def add_entity(name: str, etype: str, chunk: Chunk) -> None:
        name = _normalize_name(name)
        if len(name) < 2 or "云景" in name and etype != "公司":
            return
        key = f"{etype}::{name}"
        if key not in entities:
            entities[key] = Entity(
                entity_id=f"{kb_id}::{etype}::{name}",
                name=name,
                type=etype,
                source_chunk_ids=[chunk.chunk_id],
                source_doc_ids=[f"{chunk.source_type}:{chunk.source_id}"],
            )
        else:
            entities[key].source_chunk_ids = list(set(entities[key].source_chunk_ids + [chunk.chunk_id]))

    def add_relation(source: str, target: str, rel_type: str, chunk: Chunk) -> None:
        source = _normalize_name(source)
        target = _normalize_name(target)
        if not source or not target or source == target:
            return
        key = f"{source}::{rel_type}::{target}"
        if key not in relations:
            relations[key] = Relation(
                source=source,
                target=target,
                type=rel_type,
                source_chunk_ids=[chunk.chunk_id],
                source_doc_ids=[f"{chunk.source_type}:{chunk.source_id}"],
            )

    for chunk in chunks:
        content = chunk.content

        # 人员
        for m in person_pattern.finditer(content):
            name = m.group(1)
            if len(name) >= 2 and not any(c in name for c in "目前主要此前此前曾"):
                add_entity(name, "人员", chunk)

        # 公司
        for m in company_pattern.finditer(content):
            add_entity(m.group(1), "公司", chunk)

        # 部门
        for m in dept_pattern.finditer(content):
            add_entity(m.group(1), "部门", chunk)

        # 关系：A 向 B 汇报
        for m in re.finditer(r"([一-龥]{2,4})\s*向\s*([一-龥]{2,4})\s*汇报", content):
            add_relation(m.group(1), m.group(2), "汇报给", chunk)

        # 关系：B 的直接下属有 A
        for m in re.finditer(r"([一-龥]{2,4})\s*的?直接下属有?\s*([、，,一-龥]{2,50})", content):
            target = m.group(1)
            for name in re.findall(r"[一-龥]{2,4}", m.group(2)):
                add_relation(name, target, "汇报给", chunk)

        # 关系：A 负责 B
        for m in re.finditer(r"([一-龥]{2,4})\s*负责\s*([一-龥]{2,10}(?:部|中心))", content):
            add_relation(m.group(1), m.group(2), "负责", chunk)

        # 关系：A 任职于/加入 B
        for m in re.finditer(r"([一-龥]{2,4})\s*(?:任职于|加入)\s*([一-龥]{2,10}(?:科技|集团|软件|银行|公司))", content):
            add_relation(m.group(1), m.group(2), "任职于", chunk)

        # 关系：A 是 B 的供应商/客户
        for m in re.finditer(r"([一-龥]{2,10}(?:科技|集团|软件|银行|公司))\s*的?主要?(?:供应商|客户)\s*是?\s*([一-龥]{2,10}(?:科技|集团|软件|银行|公司))", content):
            add_relation(m.group(1), m.group(2), "供应商", chunk)
            add_relation(m.group(2), m.group(1), "客户", chunk)

        # 关系：A 代理 B
        for m in re.finditer(r"([一-龥]{2,10}(?:国信|联创|代理))\s*代理\s*([一-龥]{2,10}(?:科技|集团|软件|银行|云))", content):
            add_relation(m.group(1), m.group(2), "代理", chunk)

        # 关系：A 使用 B
        for m in re.finditer(r"([一-龥]{2,10}(?:科技|集团|制造|教育))\s*使用\s*([一-龥\w\s\/\.]+?)(?:和|与|，|,|。)", content):
            add_relation(m.group(1), m.group(2).strip(), "使用", chunk)

    return GraphExtractionResult(
        entities=list(entities.values()),
        relations=list(relations.values()),
        diagnostics={"method": "heuristic", "chunk_count": len(chunks)},
    )
