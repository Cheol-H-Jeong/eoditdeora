"""Tests for the HWP 5.x parser.

HWP 5.x is a CFBF (OLE compound) binary; synthesizing one in-process is
impractical. We instead verify the parser's integration contract by
monkeypatching `pyhwp`'s public API and exercising every branch:
success, empty, partial, and parser-error paths.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from eoditdeora.parsers.base import ParserError
from eoditdeora.parsers import hwp_parser
from eoditdeora.parsers.hwp_parser import PyhwpParser


def _install_fake_hwp5(
    monkeypatch: pytest.MonkeyPatch,
    paragraphs: list[str],
    raise_on_open: Exception | None = None,
) -> None:
    """Replace `_extract_text` with a deterministic stub for this test."""
    if raise_on_open is not None:

        def _raise(_path):  # type: ignore[no-untyped-def]
            raise raise_on_open

        monkeypatch.setattr(hwp_parser, "_extract_text", _raise)
    else:
        monkeypatch.setattr(
            hwp_parser, "_extract_text", lambda _path: "\n".join(paragraphs)
        )


def test_hwp_parser_extracts_paragraphs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _install_fake_hwp5(monkeypatch, ["첫 단락", "둘째 단락", "", "넷째 단락"])
    path = tmp_path / "doc.hwp"
    path.write_bytes(b"fake-hwp-binary")
    res = PyhwpParser().parse(path, doc_id="sha256:" + "9" * 64)
    paragraph_texts = [b.text for b in res.doc.blocks if b.type == "paragraph"]
    assert paragraph_texts == ["첫 단락", "둘째 단락", "넷째 단락"]
    assert res.doc.format == "hwp"
    assert res.doc.parser == "hwp_pyhwp"
    assert res.doc.metadata["application"] == "Hancom Office (HWP 5)"


def test_hwp_parser_empty_result_warns(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _install_fake_hwp5(monkeypatch, [])
    path = tmp_path / "empty.hwp"
    path.write_bytes(b"x")
    res = PyhwpParser().parse(path, doc_id="sha256:" + "8" * 64)
    assert res.doc.blocks == []
    assert "hwp_no_text_extracted" in res.doc.warnings


def test_hwp_parser_converts_library_errors_to_parser_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    _install_fake_hwp5(monkeypatch, [], raise_on_open=RuntimeError("bad cfb"))
    path = tmp_path / "bad.hwp"
    path.write_bytes(b"x")
    res = PyhwpParser().parse(path, doc_id="sha256:" + "7" * 64)
    assert res.doc.parse_status == "parser_error"
    assert any("bad cfb" in w for w in res.doc.warnings)


def test_hwp_parser_can_parse():
    p = PyhwpParser()
    assert p.can_parse(Path("x.hwp"))
    assert p.can_parse(Path("x.HWP"))
    assert not p.can_parse(Path("x.hwpx"))
    assert not p.can_parse(Path("x.pdf"))


def test_hwp_parser_missing_library_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """If pyhwp disappears at runtime the parser surfaces parse_status=
    parser_error so the pipeline records the file as skipped rather
    than crashing the indexer."""
    import builtins

    real_import = builtins.__import__

    def fail_import(name, *a, **k):  # type: ignore[no-untyped-def]
        if name.startswith("hwp5"):
            raise ImportError("simulated missing hwp5")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fail_import)
    path = tmp_path / "x.hwp"
    path.write_bytes(b"x")
    res = PyhwpParser().parse(path, doc_id="sha256:" + "6" * 64)
    assert res.doc.parse_status == "parser_error"
    assert any("pyhwp_not_available" in w or "simulated missing hwp5" in w for w in res.doc.warnings)
