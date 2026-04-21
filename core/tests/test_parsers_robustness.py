"""End-to-end parser robustness.

The pipeline must never surface a parser exception to callers — every
broken / empty / mis-labelled file turns into a ``parse_status`` that
the indexer records as "skipped". Exercises each built-in parser.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from eoditdeora.parsers.docx_parser import DocxParser
from eoditdeora.parsers.hwpx_parser import HwpxParser
from eoditdeora.parsers.md_parser import MdParser
from eoditdeora.parsers.pdf_parser import PdfTextLayerParser
from eoditdeora.parsers.txt_parser import TxtParser
from eoditdeora.parsers.xlsx_parser import XlsxParser

DOC_ID = "sha256:" + "a" * 64


def _parse(parser, path: Path):
    return parser.parse(path, doc_id=DOC_ID).doc


def test_empty_txt_returns_empty_status(tmp_path: Path) -> None:
    p = tmp_path / "blank.txt"
    p.write_bytes(b"")
    doc = _parse(TxtParser(), p)
    assert doc.parse_status == "empty"


def test_cp949_txt_is_recovered(tmp_path: Path) -> None:
    p = tmp_path / "k.txt"
    p.write_bytes("예산 품의서 초안".encode("cp949"))
    doc = _parse(TxtParser(), p)
    assert doc.parse_status == "ok"
    assert any("예산" in (b.text or "") for b in doc.blocks)


def test_euckr_txt_is_recovered(tmp_path: Path) -> None:
    p = tmp_path / "k.txt"
    p.write_bytes("회의록 2026".encode("euc-kr"))
    doc = _parse(TxtParser(), p)
    assert doc.parse_status == "ok"
    assert any("회의록" in (b.text or "") for b in doc.blocks)


def test_missing_file_is_file_missing(tmp_path: Path) -> None:
    doc = _parse(TxtParser(), tmp_path / "nope.txt")
    assert doc.parse_status == "file_missing"


def test_invalid_pdf_header_rejected(tmp_path: Path) -> None:
    p = tmp_path / "fake.pdf"
    p.write_bytes(b"NOT-A-PDF plain text here")
    doc = _parse(PdfTextLayerParser(), p)
    assert doc.parse_status in {"invalid_format", "parser_error"}


def test_empty_pdf_is_empty(tmp_path: Path) -> None:
    p = tmp_path / "blank.pdf"
    p.write_bytes(b"")
    doc = _parse(PdfTextLayerParser(), p)
    assert doc.parse_status == "empty"


def test_non_zip_docx_invalid_format(tmp_path: Path) -> None:
    p = tmp_path / "broken.docx"
    p.write_bytes(b"this is not a zip")
    doc = _parse(DocxParser(), p)
    assert doc.parse_status in {"invalid_format", "parser_error"}


def test_non_zip_xlsx_invalid_format(tmp_path: Path) -> None:
    p = tmp_path / "broken.xlsx"
    p.write_bytes(b"not a zip either")
    doc = _parse(XlsxParser(), p)
    assert doc.parse_status in {"invalid_format", "parser_error"}


def test_non_zip_hwpx_rejected(tmp_path: Path) -> None:
    p = tmp_path / "broken.hwpx"
    p.write_bytes(b"not a zip")
    doc = _parse(HwpxParser(), p)
    assert doc.parse_status in {"invalid_format", "parser_error"}


def test_empty_markdown_returns_empty(tmp_path: Path) -> None:
    p = tmp_path / "blank.md"
    p.write_bytes(b"")
    doc = _parse(MdParser(), p)
    assert doc.parse_status == "empty"


def test_pdf_parser_swallows_library_runtime_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Even if pypdfium2 blows up mid-parse we return parser_error
    without re-raising — the pipeline must stay alive."""
    import sys
    import types

    fake = types.ModuleType("pypdfium2")
    class _Boom:
        def __init__(self, *a, **kw) -> None:
            raise RuntimeError("pdfium exploded")
    fake.PdfDocument = _Boom  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "pypdfium2", fake)
    p = tmp_path / "x.pdf"
    # Valid header so we pass the early reject and reach the library.
    p.write_bytes(b"%PDF-1.4\n%fake body that passes the sniff\n")
    doc = _parse(PdfTextLayerParser(), p)
    assert doc.parse_status in {"parser_error", "invalid_format"}
