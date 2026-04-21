"""RPC-facing collector service."""

from __future__ import annotations

from pathlib import Path

import pytest

from eoditdeora.collector.service import add_root, remove_root, status
from eoditdeora.config import load_settings


@pytest.mark.asyncio
async def test_add_root_registers_directory(tmp_path: Path):
    result = await add_root(str(tmp_path))
    assert result["ok"] is True
    s = load_settings()
    assert str(tmp_path.resolve()) in s.index.roots


@pytest.mark.asyncio
async def test_add_root_rejects_non_directory(tmp_path: Path):
    f = tmp_path / "a.txt"
    f.write_text("x", encoding="utf-8")
    result = await add_root(str(f))
    assert result["ok"] is False
    assert result["error"] == "not_a_directory"


@pytest.mark.asyncio
async def test_add_root_is_idempotent(tmp_path: Path):
    first = await add_root(str(tmp_path))
    assert first["ok"] is True
    second = await add_root(str(tmp_path))
    assert second["ok"] is True
    assert second.get("already_registered") is True
    s = load_settings()
    resolved = str(tmp_path.resolve())
    assert s.index.roots.count(resolved) == 1


@pytest.mark.asyncio
async def test_add_root_rejects_child_of_existing_root(tmp_path: Path):
    child = tmp_path / "team"
    child.mkdir()
    await add_root(str(tmp_path))

    result = await add_root(str(child))

    assert result == {
        "ok": False,
        "error": "overlaps_existing_root",
        "path": str(child.resolve()),
        "existing_root": str(tmp_path.resolve()),
    }
    s = load_settings()
    assert s.index.roots == [str(tmp_path.resolve())]


@pytest.mark.asyncio
async def test_add_root_rejects_parent_of_existing_root(tmp_path: Path):
    child = tmp_path / "team"
    child.mkdir()
    await add_root(str(child))

    result = await add_root(str(tmp_path))

    assert result == {
        "ok": False,
        "error": "overlaps_existing_root",
        "path": str(tmp_path.resolve()),
        "existing_root": str(child.resolve()),
    }
    s = load_settings()
    assert s.index.roots == [str(child.resolve())]


@pytest.mark.asyncio
async def test_remove_root(tmp_path: Path):
    await add_root(str(tmp_path))
    r = await remove_root(str(tmp_path))
    assert r["ok"] is True
    assert r["removed"] == 1
    s = load_settings()
    assert str(tmp_path.resolve()) not in s.index.roots


@pytest.mark.asyncio
async def test_status_reports_roots_and_index(tmp_path: Path):
    await add_root(str(tmp_path))
    result = await status()
    assert str(tmp_path.resolve()) in result["roots"]
    assert "doc_count" in result["index"]
