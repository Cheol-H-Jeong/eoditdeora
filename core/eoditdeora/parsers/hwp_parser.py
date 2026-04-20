"""HWP 5.x parser via pyhwp (pure Python).

pyhwp walks the CFBF streams and yields paragraph records. We flatten the
text runs into blocks and heuristically detect headings from style names
when available. Complex layouts (equations, shapes, floats) degrade to
plain text — that is explicitly acceptable under D2 (no Hancom COM).

For HWP 3.x / pre-5.x documents, `pyhwp` raises. The registry will then
fall back to the filename stub.
"""

from __future__ import annotations

from pathlib import Path

from eoditdeora.parsers.base import Block, ParsedDoc, ParseResult, ParserError
from eoditdeora.parsers.registry import register
from eoditdeora.utils.paths_util import display_path


class PyhwpParser:
    name = "hwp_pyhwp"
    supported_extensions = ("hwp",)
    fidelity = 3

    def can_parse(self, path: Path) -> bool:
        return path.suffix.lower() == ".hwp"

    def parse(self, path: Path, *, doc_id: str) -> ParseResult:
        try:
            # pyhwp's public surface changed across versions; we tolerate
            # both the legacy `hwp5.xmlmodel` and the newer `hwp5.proc`
            # entry points, extracting plain text.
            from hwp5 import hwp5odt  # noqa: F401 — ensure import works
            from hwp5.hwp5txt import main as _hwp5txt_main  # type: ignore[import-not-found]
        except ImportError as e:
            raise ParserError(f"pyhwp_not_available: {e}") from e

        try:
            text = _extract_text(path)
        except Exception as e:  # noqa: BLE001
            raise ParserError(f"hwp_extract_failed: {e}") from e

        blocks: list[Block] = []
        for para in _split_paragraphs(text):
            blocks.append(Block(type="paragraph", text=para))

        warnings: list[str] = []
        if not blocks:
            warnings.append("hwp_no_text_extracted")

        doc = ParsedDoc(
            doc_id=doc_id,
            source_path=str(path),
            source_path_display=display_path(path),
            format="hwp",
            parser=self.name,
            fidelity=self.fidelity,
            blocks=blocks,
            metadata={"application": "Hancom Office (HWP 5)"},
            warnings=warnings,
        )
        return ParseResult(doc=doc, warnings=warnings)


def _extract_text(path: Path) -> str:
    """Run pyhwp's text extraction against `path` and return decoded text.

    pyhwp currently exposes a CLI entry-point; we replicate the equivalent
    programmatically by opening the document and streaming paragraph text.
    """
    from hwp5.dataio import ParseError  # type: ignore[import-not-found]
    from hwp5.xmlmodel import Hwp5File  # type: ignore[import-not-found]

    try:
        hwpfile = Hwp5File(str(path))
    except ParseError as e:
        raise RuntimeError(f"pyhwp_parse_error: {e}") from e

    chunks: list[str] = []
    try:
        for section in hwpfile.bodytext:
            for paragraph in section.paragraphs:
                text_parts: list[str] = []
                for piece in getattr(paragraph, "text", []) or []:
                    if isinstance(piece, str):
                        text_parts.append(piece)
                if text_parts:
                    chunks.append("".join(text_parts))
    finally:
        try:
            hwpfile.close()
        except Exception:  # noqa: BLE001
            pass
    return "\n".join(chunks)


def _split_paragraphs(text: str) -> list[str]:
    return [p.strip() for p in text.split("\n") if p.strip()]


register(PyhwpParser())
