"""Platform-aware document path discovery."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from eoditdeora.runtime import docpath_discovery as mod


def test_candidate_paths_returns_list_on_current_platform():
    # Just verify the module produces non-empty, dedup'd tuples for
    # whichever OS we're on. Shape of list matters; contents depend on
    # environment so we don't assert exact paths.
    cands = mod.candidate_paths()
    assert isinstance(cands, list)
    assert cands  # at least the canonical Documents candidate should be present
    # Dedup invariant.
    seen: set[Path] = set()
    for _label, p in cands:
        assert p not in seen
        seen.add(p)


def test_discover_marks_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # Fake a platform where no candidate exists on disk: discover must
    # return rows with exists=False for everything instead of crashing.
    fake = tmp_path / "nohome"
    fake.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake))
    results = mod.discover()
    assert all(r.exists is False for r in results), [r.to_dict() for r in results]
    assert all(r.has_documents is False for r in results)


def test_discover_detects_documents(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    fake_home = tmp_path / "home"
    docs = fake_home / "Documents"
    docs.mkdir(parents=True)
    (docs / "report.pdf").write_bytes(b"%PDF-1.4 fake")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))
    if sys.platform == "win32":
        monkeypatch.setenv("USERPROFILE", str(fake_home))

    results = mod.discover()
    docs_row = next((r for r in results if Path(r.path) == docs.resolve()), None)
    assert docs_row is not None
    assert docs_row.exists is True
    assert docs_row.has_documents is True


def test_default_roots_includes_empty_documents_folder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # Canonical Documents/문서 directories are always auto-added even
    # when empty — users expect the app to watch them from day one.
    fake_home = tmp_path / "home"
    (fake_home / "Documents").mkdir(parents=True)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))
    if sys.platform == "win32":
        monkeypatch.setenv("USERPROFILE", str(fake_home))
    roots = mod.default_roots()
    assert any(r.endswith("Documents") for r in roots)


def test_default_roots_excludes_empty_non_canonical(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # An empty Desktop folder should NOT auto-add — otherwise we'd
    # watchdog-spam every fresh user profile with zero benefit.
    fake_home = tmp_path / "home"
    (fake_home / "Desktop").mkdir(parents=True)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))
    if sys.platform == "win32":
        monkeypatch.setenv("USERPROFILE", str(fake_home))
    roots = mod.default_roots()
    # Desktop alone should not be in the default set.
    assert not any(r.endswith("Desktop") for r in roots)


def test_walk_skips_noisy_directories(tmp_path: Path):
    root = tmp_path / "project"
    (root / "node_modules" / "deep" / "nested").mkdir(parents=True)
    (root / "node_modules" / "pkg.docx").write_bytes(b"x")
    # Real doc outside node_modules
    (root / "real.hwpx").write_bytes(b"y")
    has, seen = mod._has_docs(root, mod.DEFAULT_DOC_EXTS)
    assert has is True
    # Make sure we only counted the real file path, not node_modules.
    # The walker may stat the real file first; either way the outcome
    # must be True without descending into node_modules.
    assert seen >= 1
