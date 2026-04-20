"""Shared test fixtures.

The single important thing here is isolating each test run from the
developer's real `~/.local/share/eoditdeora/` — we point EODITDEORA_HOME
at a unique tmp_path for every session.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("EODITDEORA_HOME", str(tmp_path))
    # Bust the lru_cache holding AppPaths so the new env var wins.
    try:
        from eoditdeora.config import paths as paths_mod

        paths_mod.get_paths.cache_clear()
    except ImportError:
        pass
    yield
    try:
        from eoditdeora.config import paths as paths_mod

        paths_mod.get_paths.cache_clear()
    except ImportError:
        pass
