"""Parser registry with fidelity-based fallback.

Parsers register themselves at import time. When asked to parse a file we:
  1. gather all parsers whose `supported_extensions` includes this one,
  2. sort them by fidelity (highest first),
  3. try each until one succeeds. Failures are logged, not fatal.
  4. if none succeed, return a fidelity-1 filename-only stub.
"""

from __future__ import annotations

import time
from pathlib import Path

from eoditdeora.parsers.base import (
    ParsedDoc,
    Parser,
    ParseResult,
    ParserError,
    UnsupportedFormat,
)
from eoditdeora.utils.logging import get_logger
from eoditdeora.utils.paths_util import display_path

log = get_logger(__name__)

_REGISTRY: list[Parser] = []


def register(parser: Parser) -> None:
    _REGISTRY.append(parser)


def _candidates(path: Path) -> list[Parser]:
    ext = path.suffix.lower().lstrip(".")
    if not ext:
        return []
    matches = [p for p in _REGISTRY if ext in p.supported_extensions and p.can_parse(path)]
    return sorted(matches, key=lambda p: -p.fidelity)


def resolve_parser(path: Path) -> Parser | None:
    cs = _candidates(path)
    return cs[0] if cs else None


def parse_file(path: Path, *, doc_id: str) -> ParseResult:
    """Try each candidate parser in fidelity order, falling back to a stub."""
    cs = _candidates(path)
    last_err: Exception | None = None
    for p in cs:
        started = time.monotonic()
        try:
            result = p.parse(path, doc_id=doc_id)
            result.doc.parse_ms = int((time.monotonic() - started) * 1000)
            return result
        except UnsupportedFormat:
            continue
        except ParserError as e:
            last_err = e
            log.warning("parser_error", parser=p.name, path=str(path), error=str(e))
            continue
        except Exception as e:  # noqa: BLE001
            last_err = e
            log.exception("parser_unexpected", parser=p.name, path=str(path))
            continue

    warnings = ["parse_failed_all_candidates"]
    if last_err is not None:
        warnings.append(f"last_error: {type(last_err).__name__}: {last_err}")

    stub = ParsedDoc(
        doc_id=doc_id,
        source_path=str(path),
        source_path_display=display_path(path),
        format=(path.suffix.lower().lstrip(".") or "unknown"),
        parser="filename_stub",
        fidelity=1,
        blocks=[],
        warnings=warnings,
    )
    return ParseResult(doc=stub, warnings=warnings)
