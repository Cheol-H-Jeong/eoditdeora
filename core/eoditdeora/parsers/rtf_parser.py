"""Basic RTF parser with built-in text extraction.

The app already exposes `.rtf` as a supported extension in settings, so
we need at least a plain-text extractor rather than falling back to the
filename-only stub. This parser intentionally stays dependency-free and
handles the common subset used by office-exported RTF files.
"""

from __future__ import annotations

import codecs
from pathlib import Path

from eoditdeora.parsers.base import Block, ParsedDoc, ParseResult
from eoditdeora.parsers.registry import register
from eoditdeora.utils.paths_util import display_path

_IGNORABLE_DESTINATIONS = {
    "annotation",
    "colortbl",
    "filetbl",
    "fonttbl",
    "footer",
    "footerf",
    "footerl",
    "footerr",
    "header",
    "headerf",
    "headerl",
    "headerr",
    "info",
    "listlevel",
    "listname",
    "listoverride",
    "object",
    "pict",
    "stylesheet",
}
_UNICODE_CHAR_REPLACEMENT = "\ufffd"


class RtfParser:
    name = "rtf_builtin"
    supported_extensions = ("rtf",)
    fidelity = 4

    def can_parse(self, path: Path) -> bool:
        return path.suffix.lower().lstrip(".") in self.supported_extensions

    def parse(self, path: Path, *, doc_id: str) -> ParseResult:
        if not path.exists():
            return ParseResult(
                doc=ParsedDoc(
                    doc_id=doc_id,
                    source_path=str(path),
                    source_path_display=display_path(path),
                    format="rtf",
                    parser=self.name,
                    fidelity=self.fidelity,
                    parse_status="file_missing",
                    warnings=["file_missing"],
                )
            )

        raw = path.read_bytes()
        if not raw:
            return ParseResult(
                doc=ParsedDoc(
                    doc_id=doc_id,
                    source_path=str(path),
                    source_path_display=display_path(path),
                    format="rtf",
                    parser=self.name,
                    fidelity=self.fidelity,
                    parse_status="empty",
                    warnings=["empty_file"],
                )
            )

        text = _extract_rtf_text(raw)
        if text is None:
            return ParseResult(
                doc=ParsedDoc(
                    doc_id=doc_id,
                    source_path=str(path),
                    source_path_display=display_path(path),
                    format="rtf",
                    parser=self.name,
                    fidelity=self.fidelity,
                    parse_status="invalid_format",
                    warnings=["invalid_rtf"],
                )
            )

        blocks = [Block(type="paragraph", text=p) for p in _split_paragraphs(text)]
        status = "ok" if blocks else "empty"
        warnings = [] if blocks else ["empty_text"]
        return ParseResult(
            doc=ParsedDoc(
                doc_id=doc_id,
                source_path=str(path),
                source_path_display=display_path(path),
                format="rtf",
                parser=self.name,
                fidelity=self.fidelity,
                blocks=blocks,
                parse_status=status,
                warnings=warnings,
                metadata={"extractor": "builtin_rtf"},
            ),
            warnings=warnings,
        )


def _extract_rtf_text(raw: bytes) -> str | None:
    text = raw.decode("latin-1")
    if not text.lstrip().startswith("{\\rtf"):
        return None

    out: list[str] = []
    stack: list[tuple[bool, int, str]] = []
    ignorable = False
    unicode_skip = 1
    ansi_encoding = "cp1252"
    ansi_bytes = bytearray()
    i = 0

    def _flush_ansi_bytes() -> None:
        if ignorable or not ansi_bytes:
            ansi_bytes.clear()
            return
        out.append(ansi_bytes.decode(ansi_encoding, errors="replace"))
        ansi_bytes.clear()

    while i < len(text):
        ch = text[i]
        if ch == "{":
            _flush_ansi_bytes()
            stack.append((ignorable, unicode_skip, ansi_encoding))
            i += 1
            continue
        if ch == "}":
            _flush_ansi_bytes()
            if stack:
                ignorable, unicode_skip, ansi_encoding = stack.pop()
            i += 1
            continue
        if ch != "\\":
            _flush_ansi_bytes()
            if not ignorable:
                out.append(ch)
            i += 1
            continue

        i += 1
        if i >= len(text):
            break
        token = text[i]

        if token in "\\{}":
            _flush_ansi_bytes()
            if not ignorable:
                out.append(token)
            i += 1
            continue

        if token == "'":
            if i + 2 < len(text):
                hex_code = text[i + 1 : i + 3]
                try:
                    if not ignorable:
                        ansi_bytes.append(int(hex_code, 16))
                except ValueError:
                    _flush_ansi_bytes()
                    if not ignorable:
                        out.append(_UNICODE_CHAR_REPLACEMENT)
                i += 3
                continue

        if token == "*":
            _flush_ansi_bytes()
            ignorable = True
            i += 1
            continue

        if token in ("~", "_", "-"):
            _flush_ansi_bytes()
            if not ignorable:
                out.append(" " if token == "~" else "-")
            i += 1
            continue

        if not token.isalpha():
            _flush_ansi_bytes()
            i += 1
            continue

        start = i
        while i < len(text) and text[i].isalpha():
            i += 1
        word = text[start:i]

        sign = 1
        if i < len(text) and text[i] in "+-":
            if text[i] == "-":
                sign = -1
            i += 1
        num_start = i
        while i < len(text) and text[i].isdigit():
            i += 1
        param = sign * int(text[num_start:i]) if i > num_start else None

        if word == "uc" and param is not None:
            _flush_ansi_bytes()
            unicode_skip = max(param, 0)
        elif word == "ansicpg" and param is not None:
            _flush_ansi_bytes()
            ansi_encoding = _resolve_ansicpg(param) or ansi_encoding
        elif word == "u" and param is not None:
            _flush_ansi_bytes()
            if not ignorable:
                codepoint = param if param >= 0 else param + 65536
                try:
                    out.append(chr(codepoint))
                except ValueError:
                    out.append(_UNICODE_CHAR_REPLACEMENT)
            if i < len(text) and text[i] == " ":
                i += 1
            skipped = 0
            while skipped < unicode_skip and i < len(text):
                if text[i] in "\\{}":
                    break
                i += 1
                skipped += 1
            continue
        elif word == "par":
            _flush_ansi_bytes()
            if not ignorable:
                out.append("\n\n")
        elif word == "line":
            _flush_ansi_bytes()
            if not ignorable:
                out.append("\n")
        elif word == "tab":
            _flush_ansi_bytes()
            if not ignorable:
                out.append("\t")
        elif word in ("emdash", "endash"):
            _flush_ansi_bytes()
            if not ignorable:
                out.append("-")
        elif word == "bullet":
            _flush_ansi_bytes()
            if not ignorable:
                out.append("•")
        elif word in _IGNORABLE_DESTINATIONS:
            _flush_ansi_bytes()
            ignorable = True

        if i < len(text) and text[i] == " ":
            i += 1

    _flush_ansi_bytes()
    return _normalize_text("".join(out))


def _resolve_ansicpg(codepage: int) -> str | None:
    if codepage <= 0:
        return None
    aliases = {
        65001: "utf-8",
        1200: "utf-16le",
        1201: "utf-16be",
    }
    if codepage in aliases:
        return aliases[codepage]
    try:
        return codecs.lookup(f"cp{codepage}").name
    except LookupError:
        return None


def _normalize_text(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n").strip()


def _split_paragraphs(text: str) -> list[str]:
    out: list[str] = []
    buf: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            if buf:
                out.append("\n".join(buf).strip())
                buf.clear()
            continue
        buf.append(stripped)
    if buf:
        out.append("\n".join(buf).strip())
    return [chunk for chunk in out if chunk]


register(RtfParser())
