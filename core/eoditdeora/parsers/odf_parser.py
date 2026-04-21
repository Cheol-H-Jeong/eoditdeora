"""Basic OpenDocument parser for text, spreadsheet, and presentation files.

Supports `.odt`, `.ods`, and `.odp` with no extra dependencies by reading
the XML payload from the ODF zip container.
"""

from __future__ import annotations

import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from eoditdeora.parsers.base import Block, ParsedDoc, ParseResult
from eoditdeora.parsers.registry import register
from eoditdeora.utils.paths_util import display_path

_NS = {
    "draw": "urn:oasis:names:tc:opendocument:xmlns:drawing:1.0",
    "table": "urn:oasis:names:tc:opendocument:xmlns:table:1.0",
    "text": "urn:oasis:names:tc:opendocument:xmlns:text:1.0",
}
_FORMAT_BY_EXT = {
    "odt": "odt",
    "ods": "ods",
    "odp": "odp",
}


class OpenDocumentParser:
    name = "odf_builtin"
    supported_extensions = ("odt", "ods", "odp")
    fidelity = 4

    def can_parse(self, path: Path) -> bool:
        return path.suffix.lower().lstrip(".") in self.supported_extensions

    def parse(self, path: Path, *, doc_id: str) -> ParseResult:
        fmt = _FORMAT_BY_EXT.get(path.suffix.lower().lstrip("."), "odf")
        if not path.exists():
            return ParseResult(
                doc=ParsedDoc(
                    doc_id=doc_id,
                    source_path=str(path),
                    source_path_display=display_path(path),
                    format=fmt,
                    parser=self.name,
                    fidelity=self.fidelity,
                    parse_status="file_missing",
                    warnings=["file_missing"],
                )
            )
        if path.stat().st_size == 0:
            return ParseResult(
                doc=ParsedDoc(
                    doc_id=doc_id,
                    source_path=str(path),
                    source_path_display=display_path(path),
                    format=fmt,
                    parser=self.name,
                    fidelity=self.fidelity,
                    parse_status="empty",
                    warnings=["empty_file"],
                )
            )

        try:
            with zipfile.ZipFile(path) as archive:
                content_xml = archive.read("content.xml")
                meta_xml = archive.read("meta.xml") if "meta.xml" in archive.namelist() else None
        except zipfile.BadZipFile as e:
            return ParseResult(
                doc=ParsedDoc(
                    doc_id=doc_id,
                    source_path=str(path),
                    source_path_display=display_path(path),
                    format=fmt,
                    parser=self.name,
                    fidelity=self.fidelity,
                    parse_status="invalid_format",
                    warnings=[f"odf_not_zip: {e}"],
                )
            )
        except KeyError as e:
            return ParseResult(
                doc=ParsedDoc(
                    doc_id=doc_id,
                    source_path=str(path),
                    source_path_display=display_path(path),
                    format=fmt,
                    parser=self.name,
                    fidelity=self.fidelity,
                    parse_status="invalid_format",
                    warnings=[f"odf_missing_xml: {e}"],
                )
            )
        except Exception as e:  # noqa: BLE001
            return ParseResult(
                doc=ParsedDoc(
                    doc_id=doc_id,
                    source_path=str(path),
                    source_path_display=display_path(path),
                    format=fmt,
                    parser=self.name,
                    fidelity=self.fidelity,
                    parse_status="invalid_format",
                    warnings=[f"odf_open_failed: {e}"],
                )
            )

        try:
            content_root = ET.fromstring(content_xml)
        except ET.ParseError as e:
            return ParseResult(
                doc=ParsedDoc(
                    doc_id=doc_id,
                    source_path=str(path),
                    source_path_display=display_path(path),
                    format=fmt,
                    parser=self.name,
                    fidelity=self.fidelity,
                    parse_status="invalid_format",
                    warnings=[f"odf_invalid_xml: {e}"],
                )
            )

        if fmt == "odt":
            blocks = _parse_text_blocks(content_root)
        elif fmt == "ods":
            blocks = _parse_sheet_blocks(content_root)
        else:
            blocks = _parse_presentation_blocks(content_root)

        metadata = _parse_metadata(meta_xml)
        warnings = [] if blocks else ["empty_text"]
        return ParseResult(
            doc=ParsedDoc(
                doc_id=doc_id,
                source_path=str(path),
                source_path_display=display_path(path),
                format=fmt,
                parser=self.name,
                fidelity=self.fidelity,
                blocks=blocks,
                metadata=metadata,
                parse_status="ok" if blocks else "empty",
                warnings=warnings,
            ),
            warnings=warnings,
        )


def _parse_text_blocks(root: ET.Element) -> list[Block]:
    blocks: list[Block] = []
    _walk_text_blocks(root, blocks, in_list_item=False)
    return _dedupe_blocks(blocks)


def _walk_text_blocks(elem: ET.Element, blocks: list[Block], *, in_list_item: bool) -> None:
    tag = _local_name(elem.tag)
    text = _normalize_text(_element_text(elem))
    next_in_list_item = in_list_item or tag == "list-item"

    if text:
        if tag == "h":
            level = _safe_int(elem.attrib.get(_attr_name("text", "outline-level")), fallback=1)
            blocks.append(Block(type="heading", text=text, level=max(1, min(level, 6))))
        elif tag == "list-item":
            blocks.append(Block(type="list_item", text=text))
        elif tag == "p" and not in_list_item:
            blocks.append(Block(type="paragraph", text=text))
        elif tag == "table":
            table_text, rows, cols = _table_to_text(elem)
            if table_text:
                blocks.append(Block(type="table", text=table_text, meta={"rows": rows, "cols": cols}))
            # Table content is already captured as one block. Walking into
            # child paragraphs would duplicate the same cell text.
            return

    for child in elem:
        _walk_text_blocks(child, blocks, in_list_item=next_in_list_item)


def _parse_sheet_blocks(root: ET.Element) -> list[Block]:
    blocks: list[Block] = []
    for table in root.iter():
        if _local_name(table.tag) != "table":
            continue
        sheet_name = table.attrib.get(_attr_name("table", "name")) or "Sheet"
        rows: list[list[str]] = []
        for row in table:
            if _local_name(row.tag) != "table-row":
                continue
            repeat = _safe_int(
                row.attrib.get(_attr_name("table", "number-rows-repeated")),
                fallback=1,
            )
            rendered = _render_sheet_row(row)
            if rendered:
                rows.append(rendered)
            if repeat > 1 and rendered:
                rows.extend([rendered] * min(repeat - 1, 20))
        if rows:
            blocks.append(
                Block(
                    type="table",
                    text="\n".join("\t".join(cell for cell in line) for line in rows),
                    sheet=sheet_name,
                    meta={"rows": len(rows), "cols": max((len(line) for line in rows), default=0)},
                )
            )
    return blocks


def _parse_presentation_blocks(root: ET.Element) -> list[Block]:
    blocks: list[Block] = []
    page_index = 0
    for elem in root.iter():
        if _local_name(elem.tag) != "page":
            continue
        page_index += 1
        page_name = elem.attrib.get(_attr_name("draw", "name")) or f"Slide {page_index}"
        texts: list[str] = []
        for child in elem.iter():
            tag = _local_name(child.tag)
            if tag not in {"p", "h"}:
                continue
            text = _normalize_text(_element_text(child))
            if text:
                texts.append(text)
        if texts:
            blocks.append(
                Block(
                    type="paragraph",
                    text="\n".join(texts),
                    meta={"slide": page_name},
                )
            )
    return blocks


def _parse_metadata(meta_xml: bytes | None) -> dict[str, str]:
    if not meta_xml:
        return {}
    try:
        root = ET.fromstring(meta_xml)
    except ET.ParseError:
        return {}

    metadata: dict[str, str] = {}
    for elem in root.iter():
        tag = _local_name(elem.tag)
        text = _normalize_text(_element_text(elem))
        if not text:
            continue
        if tag == "title":
            metadata["title"] = text
        elif tag == "creator":
            metadata["author"] = text
        elif tag == "description":
            metadata["description"] = text
        elif tag == "keyword":
            metadata["keywords"] = text
        elif tag == "generator":
            metadata["generator"] = text
    return metadata


def _render_sheet_row(row: ET.Element) -> list[str]:
    rendered: list[str] = []
    for cell in row:
        tag = _local_name(cell.tag)
        if tag not in {"table-cell", "covered-table-cell"}:
            continue
        text = _normalize_text(_element_text(cell))
        repeat = _safe_int(
            cell.attrib.get(_attr_name("table", "number-columns-repeated")),
            fallback=1,
        )
        rendered.extend([text] * max(1, min(repeat, 20)))
    while rendered and not rendered[-1]:
        rendered.pop()
    return rendered


def _table_to_text(table: ET.Element) -> tuple[str, int, int]:
    rows: list[list[str]] = []
    for child in table.iter():
        if _local_name(child.tag) != "table-row":
            continue
        rendered = _render_sheet_row(child)
        if rendered:
            rows.append(rendered)
    text = "\n".join("\t".join(cell for cell in row) for row in rows)
    return text, len(rows), max((len(row) for row in rows), default=0)


def _element_text(elem: ET.Element) -> str:
    parts: list[str] = []
    for text in elem.itertext():
        if text:
            parts.append(text)
    return "".join(parts)


def _normalize_text(text: str) -> str:
    return " ".join(text.replace("\r", "\n").split())


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _attr_name(ns: str, local_name: str) -> str:
    return f"{{{_NS[ns]}}}{local_name}"


def _safe_int(raw: str | None, *, fallback: int) -> int:
    if raw is None:
        return fallback
    try:
        return int(raw)
    except ValueError:
        return fallback


def _dedupe_blocks(blocks: list[Block]) -> list[Block]:
    deduped: list[Block] = []
    seen: set[tuple[str, str, int | None]] = set()
    for block in blocks:
        key = (block.type, block.text, block.level)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(block)
    return deduped


register(OpenDocumentParser())
