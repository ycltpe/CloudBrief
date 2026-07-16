from datetime import datetime

from app.stages.base import Document
from app.stages.chunking import ChunkingInput, ChunkingStage


def _doc(content: str, source_type: str = "kb_doc") -> Document:
    return Document(
        content=content,
        source_type=source_type,
        title="测试文档",
        updated_at=datetime(2026, 1, 1),
        source_id="kb/test.txt",
    )


def test_long_single_paragraph_is_hard_split():
    """OCR 场景：无空行分段的超长单段落必须按窗口硬切，且 chunk 不超过 max_chars。"""
    stage = ChunkingStage(max_chars=800, overlap_chars=100)
    content = "字" * 5000  # 扫描件 OCR 输出：整页一大段，远超 Embedding 模型输入上限

    chunks = stage.execute(ChunkingInput(documents=[_doc(content)])).chunks

    assert len(chunks) > 1
    assert all(len(c.content) <= 800 for c in chunks)
    # 窗口重叠衔接：相邻 chunk 有 overlap_chars 的重叠，总覆盖长度不小于原文
    total_covered = sum(len(c.content) for c in chunks)
    assert total_covered >= 5000


def test_long_ticket_is_hard_split():
    """ticket/faq 直出单 chunk 的路径同样受 max_chars 约束。"""
    stage = ChunkingStage(max_chars=800, overlap_chars=100)
    content = "工单内容" * 1000  # 4000 字工单

    chunks = stage.execute(
        ChunkingInput(documents=[_doc(content, source_type="ticket")])
    ).chunks

    assert len(chunks) > 1
    assert all(len(c.content) <= 800 for c in chunks)


def test_short_ticket_remains_single_chunk():
    stage = ChunkingStage(max_chars=800, overlap_chars=100)

    chunks = stage.execute(
        ChunkingInput(documents=[_doc("短工单内容", source_type="ticket")])
    ).chunks

    assert len(chunks) == 1
    assert chunks[0].content == "短工单内容"


def test_empty_content_produces_no_chunks():
    """空/纯空白文档不产生空 chunk（空文本会让 Embedding API 整批 400）。"""
    stage = ChunkingStage()

    assert stage.execute(ChunkingInput(documents=[_doc("")])).chunks == []
    assert stage.execute(ChunkingInput(documents=[_doc("   \n\n  ")])).chunks == []
    assert (
        stage.execute(
            ChunkingInput(documents=[_doc("", source_type="faq")])
        ).chunks
        == []
    )


def test_normal_paragraphs_merged_within_limit():
    """常规分段文档仍按段落合并，不超过 max_chars。"""
    stage = ChunkingStage(max_chars=800, overlap_chars=100)
    paragraphs = [f"第{i}段内容。" * 20 for i in range(5)]  # 每段约 120 字
    content = "\n\n".join(paragraphs)

    chunks = stage.execute(ChunkingInput(documents=[_doc(content)])).chunks

    assert len(chunks) == 1
    assert "第0段内容" in chunks[0].content
    assert "第4段内容" in chunks[0].content
