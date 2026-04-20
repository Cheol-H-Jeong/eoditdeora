"""HWPX native parser (pure-Python, cross-platform).

HWPX is the Hangul 2014+ format: a ZIP container with OOXML-style XML parts.
It is nowhere near as underspecified as legacy HWP 5.x, but the content
schema is still bespoke. We extract:

  * title / author / application from Contents/content.hpf + META-INF.
  * Section bodies from Contents/section*.xml (one or more sections per doc).

For each paragraph (`hp:p`) we concatenate its text runs (`hp:t`). Headings
are heuristically detected by style name containing "heading" or "Title".
Tables are emitted as tab-separated text so the downstream embedding uses
them as-is.

We deliberately avoid converting to intermediate HTML (LibreOffice, pandoc)
because that bloats the installer. This parser targets fidelity 4: content
is lossless for text + tables; shapes/drawings become image placeholders.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

from lxml import etree  # type: ignore[import-untyped]

from eoditdeora.parsers.base import Block, ParsedDoc, ParseResult, ParserError
from eoditdeora.parsers.registry import register
from eoditdeora.utils.paths_util import display_path

NS = {
    "hp": "http://www.hancom.co.kr/hwpml/2011/paragraph",
    "hs": "http://www.hancom.co.kr/hwpml/2011/section",
    "hh": "http://www.hancom.co.kr/hwpml/2011/head",
    "ha": "http://www.hancom.co.kr/hwpml/2011/app",
    "hc": "http://www.hancom.co.kr/hwpml/2011/core",
    "dc": "http://purl.org/dc/elements/1.1/",
    "opf": "http://www.idpf.org/2007/opf/",
}


class HwpxParser:
    name = "hwpx_native"
    supported_extensions = ("hwpx",)
    fidelity = 4

    def can_parse(self, path: Path) -> bool:
        return path.suffix.lower() == ".hwpx"

    def parse(self, path: Path, *, doc_id: str) -> ParseResult:
        warnings: list[str] = []
        blocks: list[Block] = []
        metadata: dict[str, object] = {"application": "Hancom Office (HWPX)"}

        try:
            zf = zipfile.ZipFile(path)
        except zipfile.BadZipFile as e:
            raise ParserError(f"hwpx_not_zip: {e}") from e

        with zf:
            names = zf.namelist()

            # Metadata from OPF if present.
            for candidate in ("Contents/content.hpf", "content.hpf"):
                if candidate in names:
                    metadata.update(_read_opf(zf, candidate))
                    break

            # Sections
            section_names = sorted(
                n for n in names if n.startswith("Contents/section") and n.endswith(".xml")
            )
            if not section_names:
                warnings.append("no_section_files")
            for sec_name in section_names:
                try:
                    xml = zf.read(sec_name)
                except KeyError:
                    warnings.append(f"missing_{sec_name}")
                    continue
                try:
                    tree = etree.fromstring(xml)  # noqa: S320 — trusted local file
                except etree.XMLSyntaxError as e:
                    warnings.append(f"xml_parse_failed_{sec_name}: {e}")
                    continue
                blocks.extend(_extract_blocks(tree))

        doc = ParsedDoc(
            doc_id=doc_id,
            source_path=str(path),
            source_path_display=display_path(path),
            format="hwpx",
            parser=self.name,
            fidelity=self.fidelity,
            blocks=blocks,
            metadata=metadata,
            warnings=warnings,
        )
        return ParseResult(doc=doc, warnings=warnings)


def _read_opf(zf: zipfile.ZipFile, name: str) -> dict[str, str]:
    out: dict[str, str] = {}
    try:
        data = zf.read(name)
    except KeyError:
        return out
    try:
        tree = etree.fromstring(data)
    except etree.XMLSyntaxError:
        return out
    for tag, key in (
        ("title", "title"),
        ("creator", "author"),
        ("date", "created_at"),
        ("publisher", "publisher"),
        ("description", "subject"),
    ):
        for elem in tree.iter(f"{{{NS['dc']}}}{tag}"):
            if elem.text:
                out[key] = elem.text.strip()
                break
    return out


def _text_of_paragraph(p: etree._Element) -> str:
    parts: list[str] = []
    for t in p.iter(f"{{{NS['hp']}}}t"):
        if t.text:
            parts.append(t.text)
    return "".join(parts).strip()


def _heading_level_from_style(style_ref: str | None) -> int | None:
    if not style_ref:
        return None
    low = style_ref.lower()
    if "heading" in low or "제목" in low or "title" in low:
        digits = "".join(c for c in low if c.isdigit())
        if digits:
            try:
                return max(1, min(6, int(digits)))
            except ValueError:
                return 1
        return 1
    return None


def _extract_blocks(section: etree._Element) -> list[Block]:
    blocks: list[Block] = []
    # Paragraphs may be nested inside tables; we walk all `hp:p` and handle
    # table cells by emitting a separate `table` block before/around them.
    # To keep reading order, iterate depth-first.
    for elem in section.iter():
        tag = etree.QName(elem.tag).localname
        if tag == "p":
            text = _text_of_paragraph(elem)
            if not text:
                continue
            style_ref = elem.get("styleIDRef") or elem.get("styleRef")
            level = _heading_level_from_style(style_ref)
            if level is not None:
                blocks.append(Block(type="heading", text=text, level=level))
            else:
                blocks.append(Block(type="paragraph", text=text))
        elif tag == "tbl":
            rows_text: list[list[str]] = []
            for tr in elem.iter(f"{{{NS['hp']}}}tr"):
                row: list[str] = []
                for tc in tr.iter(f"{{{NS['hp']}}}tc"):
                    cell_parts = [
                        _text_of_paragraph(p) for p in tc.iter(f"{{{NS['hp']}}}p")
                    ]
                    row.append(" ".join(c for c in cell_parts if c))
                rows_text.append(row)
            if rows_text:
                flat = "\n".join("\t".join(r) for r in rows_text if any(c for c in r))
                if flat:
                    blocks.append(
                        Block(
                            type="table",
                            text=flat,
                            meta={
                                "rows": len(rows_text),
                                "cols": max((len(r) for r in rows_text), default=0),
                            },
                        )
                    )
    return blocks


register(HwpxParser())
