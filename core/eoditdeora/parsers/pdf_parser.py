"""PDF parser.

Two strategies:
  * text-layer extraction via pdfplumber (fast, accurate on born-digital PDFs)
  * OCR fallback is deferred to an "understander" pass that runs on GPU;
    at parse-time we only mark images-only pages with a warning so the
    pipeline knows to schedule OCR later.
"""

from __future__ import annotations

from pathlib import Path

from eoditdeora.parsers.base import Block, ParsedDoc, ParseResult
from eoditdeora.parsers.registry import register
from eoditdeora.utils.paths_util import display_path


class PdfTextLayerParser:
    name = "pdf_pdfplumber"
    supported_extensions = ("pdf",)
    fidelity = 4

    def can_parse(self, path: Path) -> bool:
        return path.suffix.lower() == ".pdf"

    def parse(self, path: Path, *, doc_id: str) -> ParseResult:
        if not path.exists():
            return ParseResult(
                doc=ParsedDoc(
                    doc_id=doc_id,
                    source_path=str(path),
                    source_path_display=display_path(path),
                    format="pdf",
                    parser=self.name,
                    fidelity=self.fidelity,
                    parse_status="file_missing",
                    warnings=["file_missing"],
                )
            )

        try:
            size_bytes = path.stat().st_size
        except OSError as e:
            return ParseResult(
                doc=ParsedDoc(
                    doc_id=doc_id,
                    source_path=str(path),
                    source_path_display=display_path(path),
                    format="pdf",
                    parser=self.name,
                    fidelity=self.fidelity,
                    parse_status="parser_error",
                    warnings=[f"pdf_stat_failed: {e}"],
                )
            )

        if size_bytes == 0:
            return ParseResult(
                doc=ParsedDoc(
                    doc_id=doc_id,
                    source_path=str(path),
                    source_path_display=display_path(path),
                    format="pdf",
                    parser=self.name,
                    fidelity=self.fidelity,
                    parse_status="empty",
                    warnings=["empty_file"],
                )
            )

        try:
            with path.open("rb") as fp:
                header = fp.read(5)
        except OSError as e:
            return ParseResult(
                doc=ParsedDoc(
                    doc_id=doc_id,
                    source_path=str(path),
                    source_path_display=display_path(path),
                    format="pdf",
                    parser=self.name,
                    fidelity=self.fidelity,
                    parse_status="parser_error",
                    warnings=[f"pdf_open_failed: {e}"],
                )
            )

        if header != b"%PDF-":
            return ParseResult(
                doc=ParsedDoc(
                    doc_id=doc_id,
                    source_path=str(path),
                    source_path_display=display_path(path),
                    format="pdf",
                    parser=self.name,
                    fidelity=self.fidelity,
                    parse_status="invalid_format",
                    warnings=["invalid_pdf_header"],
                )
            )

        try:
            import pypdfium2  # type: ignore[import-not-found]
            import pdfplumber  # type: ignore[import-not-found]
        except ImportError as e:
            return ParseResult(
                doc=ParsedDoc(
                    doc_id=doc_id,
                    source_path=str(path),
                    source_path_display=display_path(path),
                    format="pdf",
                    parser=self.name,
                    fidelity=self.fidelity,
                    parse_status="parser_error",
                    warnings=[f"pdf_dependency_missing: {e}"],
                )
            )

        warnings: list[str] = []
        blocks: list[Block] = []
        metadata: dict[str, object] = {"application": "PDF"}

        try:
            pdfium_doc = pypdfium2.PdfDocument(str(path))
        except Exception as e:  # noqa: BLE001
            low = str(e).lower()
            parse_status = "encrypted" if ("password" in low or "encrypt" in low) else "parser_error"
            return ParseResult(
                doc=ParsedDoc(
                    doc_id=doc_id,
                    source_path=str(path),
                    source_path_display=display_path(path),
                    format="pdf",
                    parser=self.name,
                    fidelity=self.fidelity,
                    parse_status=parse_status,
                    warnings=[f"pdfium_open_failed: {e}"],
                )
            )

        try:
            encryption = getattr(pdfium_doc, "encryption", None)
            if encryption:
                return ParseResult(
                    doc=ParsedDoc(
                        doc_id=doc_id,
                        source_path=str(path),
                        source_path_display=display_path(path),
                        format="pdf",
                        parser=self.name,
                        fidelity=self.fidelity,
                        parse_status="encrypted",
                        warnings=["pdf_encrypted"],
                    )
                )
        finally:
            close = getattr(pdfium_doc, "close", None)
            if callable(close):
                close()

        try:
            pdf = pdfplumber.open(str(path))
        except Exception as e:  # noqa: BLE001
            low = str(e).lower()
            parse_status = "encrypted" if ("password" in low or "encrypt" in low) else "parser_error"
            return ParseResult(
                doc=ParsedDoc(
                    doc_id=doc_id,
                    source_path=str(path),
                    source_path_display=display_path(path),
                    format="pdf",
                    parser=self.name,
                    fidelity=self.fidelity,
                    parse_status=parse_status,
                    warnings=[f"pdf_open_failed: {e}"],
                )
            )

        with pdf:
            if pdf.metadata:
                for src, dst in (
                    ("Title", "title"),
                    ("Author", "author"),
                    ("CreationDate", "created_at"),
                    ("ModDate", "modified_at"),
                    ("Producer", "producer"),
                    ("Creator", "creator"),
                ):
                    if v := pdf.metadata.get(src):
                        metadata[dst] = str(v)
            metadata["page_count"] = len(pdf.pages)

            empty_pages = 0
            for page_no, page in enumerate(pdf.pages, start=1):
                text = (page.extract_text() or "").strip()
                page_has_content = False
                if text:
                    blocks.append(Block(type="paragraph", text=text, page=page_no))
                    page_has_content = True
                for table in page.extract_tables() or []:
                    flat = "\n".join("\t".join((c or "").strip() for c in row) for row in table)
                    if flat.strip():
                        blocks.append(Block(type="table", text=flat, page=page_no))
                        page_has_content = True
                if not page_has_content:
                    empty_pages += 1
            if empty_pages:
                warnings.append(f"ocr_needed: {empty_pages}_pages_had_no_text_layer")

        doc = ParsedDoc(
            doc_id=doc_id,
            source_path=str(path),
            source_path_display=display_path(path),
            format="pdf",
            parser=self.name,
            fidelity=self.fidelity,
            blocks=blocks,
            metadata=metadata,
            warnings=warnings,
        )
        return ParseResult(doc=doc, warnings=warnings)


register(PdfTextLayerParser())
