from pathlib import Path

from eoditdeora.parsers.pptx_parser import PptxParser

from .fixtures import make_pptx


def test_pptx_extracts_titles_and_bodies(tmp_path: Path):
    path = make_pptx(
        tmp_path / "deck.pptx",
        [
            ("2025년 계획", "핵심 목표를 세 가지로 요약합니다."),
            ("실행 전략", "분기별 로드맵과 KPI"),
        ],
    )
    res = PptxParser().parse(path, doc_id="sha256:" + "a" * 64)
    assert res.doc.format == "pptx"
    headings = [b for b in res.doc.blocks if b.type == "heading"]
    assert len(headings) == 2
    assert headings[0].text == "2025년 계획"
    paragraphs = [b for b in res.doc.blocks if b.type == "paragraph"]
    assert any("KPI" in p.text for p in paragraphs)


def test_pptx_page_count_metadata(tmp_path: Path):
    path = make_pptx(tmp_path / "d.pptx", [("A", "a"), ("B", "b"), ("C", "c")])
    res = PptxParser().parse(path, doc_id="sha256:" + "b" * 64)
    assert res.doc.metadata.get("page_count") == 3
