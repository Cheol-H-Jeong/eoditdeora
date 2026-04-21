"""Plain text parser with charset sniffing."""

from __future__ import annotations

from pathlib import Path

from eoditdeora.parsers.base import Block, ParsedDoc, ParseResult
from eoditdeora.parsers.registry import register
from eoditdeora.utils.paths_util import display_path

_ENCODINGS = ("utf-8", "cp949", "euc-kr")


class TxtParser:
    name = "txt_plain"
    supported_extensions = ("txt", "log", "ini", "cfg", "env")
    fidelity = 5

    def can_parse(self, path: Path) -> bool:
        return path.suffix.lower().lstrip(".") in self.supported_extensions

    def parse(self, path: Path, *, doc_id: str) -> ParseResult:
        if not path.exists():
            return ParseResult(
                doc=ParsedDoc(
                    doc_id=doc_id,
                    source_path=str(path),
                    source_path_display=display_path(path),
                    format="txt",
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
                    format="txt",
                    parser=self.name,
                    fidelity=self.fidelity,
                    parse_status="empty",
                    warnings=["empty_file"],
                )
            )

        text, encoding_used = _decode(raw)
        if text is None:
            return ParseResult(
                doc=ParsedDoc(
                    doc_id=doc_id,
                    source_path=str(path),
                    source_path_display=display_path(path),
                    format="txt",
                    parser=self.name,
                    fidelity=self.fidelity,
                    parse_status="invalid_format",
                    warnings=["no_compatible_encoding"],
                )
            )
        blocks = [Block(type="paragraph", text=p) for p in _split_paragraphs(text)]
        doc = ParsedDoc(
            doc_id=doc_id,
            source_path=str(path),
            source_path_display=display_path(path),
            format="txt",
            parser=self.name,
            fidelity=self.fidelity,
            blocks=blocks,
            metadata={"encoding": encoding_used},
        )
        return ParseResult(doc=doc)


def _decode(raw: bytes) -> tuple[str | None, str | None]:
    for enc in _ENCODINGS:
        try:
            return raw.decode(enc), enc
        except UnicodeDecodeError:
            continue
    return None, None


def _split_paragraphs(text: str) -> list[str]:
    out: list[str] = []
    buf: list[str] = []
    for line in text.splitlines():
        if not line.strip():
            if buf:
                out.append("\n".join(buf).strip())
                buf.clear()
        else:
            buf.append(line)
    if buf:
        out.append("\n".join(buf).strip())
    return [p for p in out if p]


register(TxtParser())
