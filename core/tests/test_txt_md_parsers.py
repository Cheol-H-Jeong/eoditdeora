from pathlib import Path

from eoditdeora.parsers.md_parser import MdParser
from eoditdeora.parsers.txt_parser import TxtParser


def test_txt_parser_utf8(tmp_path: Path):
    f = tmp_path / "hello.txt"
    f.write_text("첫 번째 문단\n\n두 번째 문단", encoding="utf-8")
    res = TxtParser().parse(f, doc_id="sha256:" + "b" * 64)
    assert res.doc.format == "txt"
    assert len(res.doc.blocks) == 2
    assert res.doc.metadata["encoding"] == "utf-8"


def test_txt_parser_cp949(tmp_path: Path):
    f = tmp_path / "legacy.txt"
    f.write_bytes("한글 레거시".encode("cp949"))
    res = TxtParser().parse(f, doc_id="sha256:" + "c" * 64)
    assert res.doc.metadata["encoding"] == "cp949"
    assert res.doc.blocks[0].text.startswith("한글")


def test_md_parser_headings_and_frontmatter(tmp_path: Path):
    f = tmp_path / "note.md"
    f.write_text(
        "---\n"
        "author: cheol\n"
        "---\n"
        "# 제목\n"
        "본문입니다.\n\n"
        "## 하위제목\n"
        "다음 문단.",
        encoding="utf-8",
    )
    res = MdParser().parse(f, doc_id="sha256:" + "d" * 64)
    assert res.doc.metadata == {"author": "cheol"}
    kinds = [(b.type, b.level) for b in res.doc.blocks]
    assert ("heading", 1) in kinds
    assert ("heading", 2) in kinds
    assert any(b.type == "paragraph" for b in res.doc.blocks)
