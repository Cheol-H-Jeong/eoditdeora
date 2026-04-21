from pathlib import Path
import sys
import types

import pytest

from eoditdeora.parsers.pdf_parser import PdfTextLayerParser

from .fixtures import make_pdf


def test_pdf_text_layer_extracted(tmp_path: Path):
    # Minimal synthesized PDF only supports Latin-1 since embedding a
    # Korean-capable font would pull in reportlab. The parser logic we
    # verify is script-agnostic.
    path = make_pdf(
        tmp_path / "budget.pdf",
        [
            "Budget Increase Proposal",
            "Project: Welfare Enhancement 2025",
            "Requested: KRW 120,000,000",
        ],
    )
    res = PdfTextLayerParser().parse(path, doc_id="sha256:" + "c" * 64)
    assert res.doc.format == "pdf"
    assert res.doc.parser == "pdf_pdfplumber"
    text = "\n".join(b.text for b in res.doc.blocks)
    assert "Budget" in text
    assert "Welfare" in text
    assert res.doc.metadata.get("page_count") == 1


def test_pdf_reports_no_ocr_needed_for_text_layer(tmp_path: Path):
    path = make_pdf(tmp_path / "t.pdf", ["Has content"])
    res = PdfTextLayerParser().parse(path, doc_id="sha256:" + "d" * 64)
    assert not any("ocr_needed" in w for w in res.doc.warnings)


def test_pdf_table_only_page_does_not_trigger_ocr_needed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    path = tmp_path / "table-only.pdf"
    path.write_bytes(b"%PDF-1.4\n%fake but header-valid\n")

    fake_pdfium = types.ModuleType("pypdfium2")

    class _FakePdfiumDoc:
        encryption = None

        def __init__(self, _path: str) -> None:
            pass

        def close(self) -> None:
            pass

    fake_pdfium.PdfDocument = _FakePdfiumDoc  # type: ignore[attr-defined]

    fake_pdfplumber = types.ModuleType("pdfplumber")

    class _FakePage:
        def extract_text(self) -> str:
            return ""

        def extract_tables(self) -> list[list[list[str]]]:
            return [[["항목", "금액"], ["예산안", "120000000"]]]

    class _FakePdf:
        metadata = {}
        pages = [_FakePage()]

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

    def _open(_path: str) -> _FakePdf:
        return _FakePdf()

    fake_pdfplumber.open = _open  # type: ignore[attr-defined]

    monkeypatch.setitem(sys.modules, "pypdfium2", fake_pdfium)
    monkeypatch.setitem(sys.modules, "pdfplumber", fake_pdfplumber)

    res = PdfTextLayerParser().parse(path, doc_id="sha256:" + "f" * 64)

    assert not any("ocr_needed" in w for w in res.doc.warnings)
    assert any(block.type == "table" and "예산안" in block.text for block in res.doc.blocks)


def test_pdf_preflight_avoids_reading_entire_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    path = tmp_path / "fake.pdf"
    path.write_bytes(b"%PDF-1.7\nnot really a pdf body")

    def _read_bytes(self: Path) -> bytes:
        raise AssertionError("read_bytes should not be used for PDF preflight")

    monkeypatch.setattr(Path, "read_bytes", _read_bytes)

    res = PdfTextLayerParser().parse(path, doc_id="sha256:" + "e" * 64)
    assert res.doc.parse_status in {"parser_error", "invalid_format"}
