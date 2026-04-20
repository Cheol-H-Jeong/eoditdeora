from pathlib import Path

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
