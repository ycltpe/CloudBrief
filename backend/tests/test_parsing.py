
from app.stages.parsing import NativeParser


def test_parse_file_md(tmp_path):
    data_dir = tmp_path / "data"
    kb_dir = data_dir / "kb" / "dir_1"
    kb_dir.mkdir(parents=True)
    file_path = kb_dir / "test.md"
    file_path.write_text("---\ntitle: Hello\n---\n# World\n\ncontent", encoding="utf-8")

    parser = NativeParser(data_dir)
    docs = parser.parse_file(file_path)

    assert len(docs) == 1
    assert docs[0].title == "Hello"
    assert "World" in docs[0].content
    assert docs[0].source_id == "kb/dir_1/test.md"


def test_parse_file_txt(tmp_path):
    data_dir = tmp_path / "data"
    kb_dir = data_dir / "kb"
    kb_dir.mkdir(parents=True)
    file_path = kb_dir / "note.txt"
    file_path.write_text("plain text", encoding="utf-8")

    parser = NativeParser(data_dir)
    docs = parser.parse_file(file_path)

    assert len(docs) == 1
    assert docs[0].content == "plain text"
    assert docs[0].source_type == "kb_doc"


def test_parse_file_unsupported(tmp_path):
    data_dir = tmp_path / "data"
    file_path = data_dir / "x.pdf"
    file_path.parent.mkdir(parents=True)
    file_path.write_text("x")

    parser = NativeParser(data_dir)
    assert parser.parse_file(file_path) == []
