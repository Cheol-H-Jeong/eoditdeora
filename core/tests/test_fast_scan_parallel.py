from __future__ import annotations

from pathlib import Path

from eoditdeora.indexer.fast_scan import _scan_root_impl, scan_root
from eoditdeora.storage.fast_index import FastIndex


def _make_tree(root: Path, count: int) -> set[str]:
    expected: set[str] = set()
    for bucket in range(5):
        subdir = root / f"dir_{bucket}" / "nested"
        subdir.mkdir(parents=True, exist_ok=True)
    for idx in range(count):
        target = root / f"dir_{idx % 5}" / "nested" / f"doc_{idx:03d}.txt"
        target.write_text("", encoding="utf-8")
        expected.add(str(target.resolve()))
    (root / "node_modules").mkdir()
    (root / "node_modules" / "ignored.txt").write_text("", encoding="utf-8")
    (root / ".git").mkdir()
    (root / ".git" / "HEAD").write_text("ref", encoding="utf-8")
    return expected


def _paths_in_index() -> set[str]:
    idx = FastIndex()
    try:
        return {row.path for row in idx.search("doc_", limit=1000)}
    finally:
        idx.close()


def test_parallel_scan_matches_sequential(tmp_path: Path):
    root = tmp_path / "docs"
    root.mkdir()
    expected = _make_tree(root, 100)

    seen_seq, up_seq = _scan_root_impl(root, {".txt"}, 0, max_workers=1)
    seq_paths = _paths_in_index()

    idx = FastIndex()
    try:
        assert idx.delete_under(root) == 100
    finally:
        idx.close()

    seen_par, up_par = scan_root(root, {".txt"}, 0)
    par_paths = _paths_in_index()

    assert (seen_seq, up_seq) == (100, 100)
    assert (seen_par, up_par) == (seen_seq, up_seq)
    assert seq_paths == expected
    assert par_paths == expected


def test_scan_root_rescan_twice_without_deadlock(tmp_path: Path):
    root = tmp_path / "docs"
    root.mkdir()
    _make_tree(root, 100)

    first = scan_root(root, {".txt"}, 0)
    second = scan_root(root, {".txt"}, 0)

    idx = FastIndex()
    try:
        assert idx.count() == 100
    finally:
        idx.close()

    assert first == (100, 100)
    assert second == (100, 100)


def test_scan_root_empty_root(tmp_path: Path):
    root = tmp_path / "empty"
    root.mkdir()

    assert scan_root(root, {".txt"}, 0) == (0, 0)
