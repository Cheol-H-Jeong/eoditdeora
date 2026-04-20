"""Registry fallback semantics."""

from __future__ import annotations

from pathlib import Path

import pytest

from eoditdeora.parsers.base import (
    Block,
    ParsedDoc,
    ParseResult,
    ParserError,
    UnsupportedFormat,
)
from eoditdeora.parsers.registry import _REGISTRY, parse_file, register, resolve_parser


def _doc(parser: str, text: str) -> ParsedDoc:
    return ParsedDoc(
        doc_id="sha256:" + "1" * 64,
        source_path="/tmp/x",
        source_path_display="/tmp/x",
        format="test",
        parser=parser,
        fidelity=1,
        blocks=[Block(type="paragraph", text=text)],
    )


class _Always:
    name = "_test_always"
    supported_extensions = ("tstalways",)
    fidelity = 5

    def can_parse(self, path: Path) -> bool:
        return path.suffix.lower() == ".tstalways"

    def parse(self, path: Path, *, doc_id: str) -> ParseResult:
        return ParseResult(doc=_doc(self.name, "ok"))


class _FailLowFidelity:
    name = "_test_fail_low"
    supported_extensions = ("tstfall",)
    fidelity = 2

    def can_parse(self, path: Path) -> bool:
        return path.suffix.lower() == ".tstfall"

    def parse(self, path: Path, *, doc_id: str) -> ParseResult:
        raise ParserError("low_failed")


class _SucceedHighFidelity:
    name = "_test_succeed_high"
    supported_extensions = ("tstfall",)
    fidelity = 4

    def can_parse(self, path: Path) -> bool:
        return path.suffix.lower() == ".tstfall"

    def parse(self, path: Path, *, doc_id: str) -> ParseResult:
        raise ParserError("high_failed")


class _FallbackParser:
    name = "_test_fallback"
    supported_extensions = ("tstfall",)
    fidelity = 3

    def can_parse(self, path: Path) -> bool:
        return path.suffix.lower() == ".tstfall"

    def parse(self, path: Path, *, doc_id: str) -> ParseResult:
        return ParseResult(doc=_doc(self.name, "fallback"))


@pytest.fixture(autouse=True)
def _register_test_parsers():
    before = list(_REGISTRY)
    register(_Always())
    register(_FailLowFidelity())
    register(_SucceedHighFidelity())
    register(_FallbackParser())
    yield
    _REGISTRY[:] = before


def test_resolve_picks_highest_fidelity(tmp_path: Path):
    p = tmp_path / "x.tstfall"
    p.write_bytes(b"x")
    chosen = resolve_parser(p)
    assert chosen is not None
    assert chosen.name == "_test_succeed_high"


def test_parse_file_falls_through_to_working_parser(tmp_path: Path):
    p = tmp_path / "x.tstfall"
    p.write_bytes(b"x")
    res = parse_file(p, doc_id="sha256:" + "1" * 64)
    assert res.doc.parser == "_test_fallback"


def test_parse_file_all_fail_returns_filename_stub(tmp_path: Path):
    # Extension with only failing parsers — we monkeypatch _FallbackParser to
    # fail too by removing it from the registry temporarily.
    _REGISTRY[:] = [r for r in _REGISTRY if r.name != "_test_fallback"]
    p = tmp_path / "x.tstfall"
    p.write_bytes(b"x")
    res = parse_file(p, doc_id="sha256:" + "2" * 64)
    assert res.doc.parser == "filename_stub"
    assert res.doc.fidelity == 1
    assert res.doc.warnings[0] == "parse_failed_all_candidates"


def test_parse_file_unsupported_extension_returns_stub(tmp_path: Path):
    p = tmp_path / "x.totallymadeup"
    p.write_bytes(b"x")
    res = parse_file(p, doc_id="sha256:" + "3" * 64)
    assert res.doc.parser == "filename_stub"


def test_parse_file_records_parse_ms(tmp_path: Path):
    p = tmp_path / "x.tstalways"
    p.write_bytes(b"x")
    res = parse_file(p, doc_id="sha256:" + "4" * 64)
    assert isinstance(res.doc.parse_ms, int)
    assert res.doc.parse_ms >= 0


class _UnsupportedParser:
    """Returns UnsupportedFormat to prove the registry tries the next one."""

    name = "_test_unsupported"
    supported_extensions = ("tstuns",)
    fidelity = 5

    def can_parse(self, path: Path) -> bool:
        return path.suffix.lower() == ".tstuns"

    def parse(self, path: Path, *, doc_id: str) -> ParseResult:
        raise UnsupportedFormat("always")


class _ConsistentLow:
    name = "_test_consistent"
    supported_extensions = ("tstuns",)
    fidelity = 2

    def can_parse(self, path: Path) -> bool:
        return path.suffix.lower() == ".tstuns"

    def parse(self, path: Path, *, doc_id: str) -> ParseResult:
        return ParseResult(doc=_doc(self.name, "ok"))


def test_unsupported_format_bypasses_to_lower_fidelity(tmp_path: Path):
    register(_UnsupportedParser())
    register(_ConsistentLow())
    p = tmp_path / "x.tstuns"
    p.write_bytes(b"x")
    res = parse_file(p, doc_id="sha256:" + "5" * 64)
    assert res.doc.parser == "_test_consistent"
