from pathlib import Path

from eoditdeora.parsers.hwpx_parser import HwpxParser

from .fixtures import make_hwpx


def test_hwpx_native_parses_minimal_doc(tmp_path: Path):
    path = make_hwpx(
        tmp_path / "doc.hwpx",
        title="테스트 문서",
        paragraphs=[
            "첫 번째 단락입니다.",
            "두 번째 단락은 조금 더 깁니다. 본문은 한국어로 작성됩니다.",
            "세 번째 단락입니다.",
        ],
    )
    res = HwpxParser().parse(path, doc_id="sha256:" + "e" * 64)
    assert res.doc.format == "hwpx"
    assert res.doc.parser == "hwpx_native"
    paragraphs = [b.text for b in res.doc.blocks if b.type == "paragraph"]
    assert len(paragraphs) == 3
    assert paragraphs[0].startswith("첫")
    assert res.doc.metadata.get("title") == "테스트 문서"
    assert res.doc.metadata.get("author") == "tester"


def test_hwpx_corrupt_zip_returns_invalid_format(tmp_path: Path):
    path = tmp_path / "bad.hwpx"
    path.write_bytes(b"not a zip")
    res = HwpxParser().parse(path, doc_id="sha256:" + "f" * 64)
    assert res.doc.parse_status in {"invalid_format", "parser_error"}
    assert any("zip" in w.lower() or "bad" in w.lower() for w in res.doc.warnings)


def test_hwpx_no_sections_warns(tmp_path: Path):
    import zipfile

    path = tmp_path / "empty.hwpx"
    with zipfile.ZipFile(path, "w") as zf:
        info = zipfile.ZipInfo("mimetype")
        info.compress_type = zipfile.ZIP_STORED
        zf.writestr(info, b"application/hwp+zip")
    res = HwpxParser().parse(path, doc_id="sha256:" + "0" * 64)
    assert "no_section_files" in res.doc.warnings
