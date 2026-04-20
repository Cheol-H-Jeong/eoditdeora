"""Parser protocol and data shapes.

Each parser implements a single `parse()` method that returns a `ParseResult`.
A parse is allowed to fail in one of three ways:

* raise `UnsupportedFormat`: this parser cannot handle the file; the
  registry should try the next candidate.
* return a `ParseResult` with `warnings` populated: partial success.
* raise `ParserError` with a message: terminal failure for this parser,
  registry falls back to the next.

The registry guarantees at minimum a fidelity-1 result (filename-only) so
downstream code can always assume a `ParsedDoc` exists.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, Field


class Block(BaseModel):
    type: str  # heading|paragraph|table|list_item|code|footnote|caption|image_ref|formula|quote|other
    text: str
    level: int | None = None
    page: int | None = None
    sheet: str | None = None
    bbox: tuple[float, float, float, float] | None = None
    meta: dict[str, Any] = Field(default_factory=dict)


class Image(BaseModel):
    id: str
    cache_path: str
    width: int | None = None
    height: int | None = None
    caption: str | None = None
    ocr_text: str | None = None


class ParsedDoc(BaseModel):
    """Conforms to schemas/parsed_doc.schema.json."""

    doc_id: str
    source_path: str
    source_path_display: str
    format: str
    parser: str
    fidelity: int = Field(ge=1, le=5)
    blocks: list[Block] = Field(default_factory=list)
    images: list[Image] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    parse_ms: int | None = None


@dataclass
class ParseResult:
    doc: ParsedDoc
    warnings: list[str] = field(default_factory=list)


class UnsupportedFormat(Exception):
    """Raised when a parser is handed a file it cannot process at all."""


class ParserError(Exception):
    """Raised when parsing starts but cannot finish."""


class Parser(Protocol):
    """Parser contract. Keep it narrow so plugins are easy to add."""

    name: str
    supported_extensions: tuple[str, ...]
    fidelity: int

    def can_parse(self, path: Path) -> bool: ...

    def parse(self, path: Path, *, doc_id: str) -> ParseResult: ...
