"""Everything-tier file-name index."""

from __future__ import annotations

from pathlib import Path

import pytest

from eoditdeora.storage.fast_index import FastIndex


@pytest.fixture
def idx(tmp_path: Path) -> FastIndex:
    return FastIndex(db_path=tmp_path / "fast.db")


def test_upsert_and_count(idx: FastIndex):
    assert idx.count() == 0
    idx.upsert("/a/b/file.txt", size=100, mtime=1700000000.0)
    assert idx.count() == 1


def test_upsert_is_idempotent(idx: FastIndex):
    idx.upsert("/a/b/file.txt", size=100, mtime=1700000000.0)
    idx.upsert("/a/b/file.txt", size=200, mtime=1700000010.0)
    assert idx.count() == 1
    rows = idx.search("file")
    assert len(rows) == 1
    assert rows[0].size == 200  # updated


def test_trigram_substring_match(idx: FastIndex):
    idx.upsert_many([
        ("/x/2025-1Q_report.hwpx", 1, 100.0),
        ("/x/2025-2Q_plan.docx", 1, 100.0),
        ("/x/summary.pdf", 1, 100.0),
    ])
    # Substring in the middle of a name — only trigram can catch this.
    names = {r.name for r in idx.search("report")}
    assert "2025-1Q_report.hwpx" in names
    names = {r.name for r in idx.search("2025")}
    assert "2025-1Q_report.hwpx" in names and "2025-2Q_plan.docx" in names
    # Korean substring.
    idx.upsert("/x/2025_보고서.hwpx", size=1, mtime=100.0)
    assert any("보고" in r.name for r in idx.search("보고"))


def test_ext_filter(idx: FastIndex):
    idx.upsert_many([
        ("/x/report_a.hwpx", 1, 100.0),
        ("/x/report_b.pdf", 1, 100.0),
        ("/x/report_c.docx", 1, 100.0),
    ])
    rows = idx.search("report", exts=[".hwpx", ".pdf"])
    got = sorted(r.ext for r in rows)
    assert got == [".hwpx", ".pdf"]


def test_delete(idx: FastIndex):
    idx.upsert("/x/a.hwpx", 1, 100.0)
    idx.delete("/x/a.hwpx")
    assert idx.count() == 0
    assert idx.search("a") == []


def test_delete_under(idx: FastIndex):
    idx.upsert_many([
        ("/root/keep/a.txt", 1, 100.0),
        ("/root/drop/b.txt", 1, 100.0),
        ("/root/drop/nested/c.txt", 1, 100.0),
    ])
    deleted = idx.delete_under("/root/drop")
    assert deleted == 2
    remaining = {r.path for r in idx.search("txt")}
    assert remaining == {"/root/keep/a.txt"}


def test_delete_under_escapes_like_metacharacters(idx: FastIndex):
    # Pre-fix `_` was not escaped in LIKE patterns, so deleting under
    # `/home/x/my_docs/` would also have matched `/home/x/myAdocs/`.
    # Verify the underscore in the root name no longer wildcards.
    idx.upsert_many([
        ("/home/x/my_docs/keep.txt", 1, 100.0),
        ("/home/x/myAdocs/innocent.txt", 1, 100.0),
    ])
    deleted = idx.delete_under("/home/x/my_docs")
    assert deleted == 1
    paths = {r.path for r in idx.search("txt")}
    assert "/home/x/myAdocs/innocent.txt" in paths
    assert "/home/x/my_docs/keep.txt" not in paths


def test_delete_missing_under_keeps_seen_paths_only(idx: FastIndex):
    idx.upsert_many([
        ("/root/docs/keep.txt", 1, 100.0),
        ("/root/docs/drop.txt", 1, 100.0),
        ("/root/other/untouched.txt", 1, 100.0),
    ])
    deleted = idx.delete_missing_under("/root/docs", {"/root/docs/keep.txt"})
    assert deleted == 1
    paths = {r.path for r in idx.search("txt")}
    assert paths == {"/root/docs/keep.txt", "/root/other/untouched.txt"}


def test_stats_by_ext(idx: FastIndex):
    idx.upsert_many([
        ("/x/a.pdf", 1, 100.0),
        ("/x/b.pdf", 1, 100.0),
        ("/x/c.docx", 1, 100.0),
    ])
    stats = dict(idx.stats_by_ext())
    assert stats[".pdf"] == 2
    assert stats[".docx"] == 1


def test_empty_query_returns_empty(idx: FastIndex):
    idx.upsert("/x/a.txt", 1, 100.0)
    assert idx.search("") == []
    assert idx.search("   ") == []


def test_limit_is_respected(idx: FastIndex):
    idx.upsert_many([(f"/x/file{i:03d}.txt", 1, 100.0) for i in range(20)])
    rows = idx.search("file", limit=5)
    assert len(rows) == 5


def test_negative_limit_does_not_disable_cap(idx: FastIndex):
    idx.upsert_many([(f"/x/file{i:03d}.txt", 1, 100.0 + i) for i in range(5)])
    assert idx.search("file", limit=-1) == []
