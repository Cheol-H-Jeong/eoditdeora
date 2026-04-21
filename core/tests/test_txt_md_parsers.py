from pathlib import Path

from eoditdeora.parsers.md_parser import MdParser
from eoditdeora.parsers.rtf_parser import RtfParser
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


def test_rtf_parser_extracts_unicode_text_and_paragraphs(tmp_path: Path):
    f = tmp_path / "memo.rtf"
    f.write_text(
        "{\\rtf1\\ansi\\ansicpg949\\deff0\\uc1 "
        "{\\fonttbl{\\f0\\fnil Gulim;}}"
        "\\viewkind4\\pard "
        "\\u-14840?\\u-16208? \\u-11128?\\u-14504?\\u-16100?\\par "
        "\\u-10612?\\u-14504?\\u-18339? 2026\\par}",
        encoding="latin-1",
    )
    res = RtfParser().parse(f, doc_id="sha256:" + "e" * 64)
    assert res.doc.format == "rtf"
    assert res.doc.parse_status == "ok"
    assert [b.text for b in res.doc.blocks] == ["예산 품의서", "회의록 2026"]


def test_rtf_parser_ignores_metadata_groups_and_decodes_hex_escapes(tmp_path: Path):
    f = tmp_path / "latin.rtf"
    f.write_text(
        "{\\rtf1\\ansi"
        "{\\info{\\title Hidden Title}}"
        "\\pard Caf\\'e9 budget\\tab draft\\par}",
        encoding="latin-1",
    )
    res = RtfParser().parse(f, doc_id="sha256:" + "f" * 64)
    assert res.doc.parse_status == "ok"
    assert [b.text for b in res.doc.blocks] == ["Café budget\tdraft"]
