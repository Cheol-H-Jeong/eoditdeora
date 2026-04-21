"""RPC-facing collector service."""

from __future__ import annotations

from pathlib import Path

import pytest

from eoditdeora.collector.service import add_root, remove_root, status
from eoditdeora.config import load_settings
from eoditdeora.storage.fast_index import FastIndex
from eoditdeora.storage.fts import FtsStore
from eoditdeora.storage.meta import MetaStore


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
    draft = tmp_path / "draft.txt"
    draft.write_text("x", encoding="utf-8")
    await add_root(str(tmp_path))
    r = await remove_root(str(tmp_path))
    assert r["ok"] is True
    assert r["removed"] == 1
    s = load_settings()
    assert str(tmp_path.resolve()) not in s.index.roots
    idx = FastIndex()
    try:
        assert idx.search("draft") == []
    finally:
        idx.close()


@pytest.mark.asyncio
async def test_remove_root_purges_body_search_content_for_removed_root(tmp_path: Path):
    removed_root = tmp_path / "removed"
    kept_root = tmp_path / "kept"
    removed_root.mkdir()
    kept_root.mkdir()

    removed_doc_path = removed_root / "draft.txt"
    kept_doc_path = kept_root / "keep.txt"
    removed_doc_path.write_text("예산 취소 초안", encoding="utf-8")
    kept_doc_path.write_text("예산 승인 문서", encoding="utf-8")

    await add_root(str(removed_root))
    await add_root(str(kept_root))

    meta = MetaStore()
    fts = FtsStore()
    try:
        meta.upsert_document(
            {
                "doc_id": "sha256:" + "a" * 64,
                "root": str(removed_root.resolve()),
                "source_path": str(removed_doc_path.resolve()),
                "source_path_display": str(removed_doc_path.resolve()),
                "format": "txt",
                "parser": "txt_plain",
                "fidelity": 5,
                "size_bytes": 1,
                "mtime_ns": 1,
                "indexed_at": 1,
                "classification": None,
                "summary_oneline": "삭제 대상",
                "summary_paragraph": None,
                "summary_detailed": None,
                "language": None,
                "warnings_json": "[]",
                "metadata_json": "{}",
            }
        )
        meta.upsert_document(
            {
                "doc_id": "sha256:" + "b" * 64,
                "root": str(kept_root.resolve()),
                "source_path": str(kept_doc_path.resolve()),
                "source_path_display": str(kept_doc_path.resolve()),
                "format": "txt",
                "parser": "txt_plain",
                "fidelity": 5,
                "size_bytes": 1,
                "mtime_ns": 1,
                "indexed_at": 1,
                "classification": None,
                "summary_oneline": "유지 대상",
                "summary_paragraph": None,
                "summary_detailed": None,
                "language": None,
                "warnings_json": "[]",
                "metadata_json": "{}",
            }
        )
        fts.upsert(
            [
                {
                    "chunk_id": "c-removed",
                    "doc_id": "sha256:" + "a" * 64,
                    "text": "예산 취소 초안",
                },
                {
                    "chunk_id": "c-kept",
                    "doc_id": "sha256:" + "b" * 64,
                    "text": "예산 승인 문서",
                },
            ]
        )
    finally:
        meta.close()

    result = await remove_root(str(removed_root))

    check_meta = MetaStore()
    check_fts = FtsStore()
    try:
        assert result["content_docs_removed"] == 1
        assert check_meta.get_document("sha256:" + "a" * 64) is None
        assert check_meta.get_document("sha256:" + "b" * 64) is not None
        assert {row["chunk_id"] for row in check_fts.search("예산", top_k=10)} == {
            "c-kept"
        }
    finally:
        check_meta.close()


@pytest.mark.asyncio
async def test_status_reports_roots_and_index(tmp_path: Path):
    await add_root(str(tmp_path))
    result = await status()
    assert str(tmp_path.resolve()) in result["roots"]
    assert "doc_count" in result["index"]
