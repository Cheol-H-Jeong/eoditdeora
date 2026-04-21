from pathlib import Path

from eoditdeora.collector.ignore import IgnoreMatcher
from eoditdeora.collector.model import ChangeKind
from eoditdeora.collector.scanner import Scanner


def test_scanner_yields_each_file(tmp_path: Path):
    scan_root = tmp_path / "scan"
    scan_root.mkdir()
    (scan_root / "a.txt").write_text("a", encoding="utf-8")
    (scan_root / "sub").mkdir()
    (scan_root / "sub" / "b.txt").write_text("b", encoding="utf-8")
    (scan_root / "sub" / "c.md").write_text("c", encoding="utf-8")

    results = list(Scanner(scan_root).walk())
    names = sorted(r.path.name for r in results)
    assert names == ["a.txt", "b.txt", "c.md"]
    assert all(r.change is ChangeKind.CREATED for r in results)


def test_scanner_respects_ignore_patterns(tmp_path: Path):
    (tmp_path / "keep.txt").write_text("k", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "ignored.js").write_text("x", encoding="utf-8")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "HEAD").write_text("ref", encoding="utf-8")

    results = list(Scanner(tmp_path).walk())
    names = [r.path.name for r in results]
    assert names == ["keep.txt"]


def test_scanner_skips_oversize_files(tmp_path: Path):
    small = tmp_path / "small.txt"
    small.write_bytes(b"ok")
    big = tmp_path / "big.bin"
    big.write_bytes(b"0" * 100)

    results = list(Scanner(tmp_path, max_bytes=10).walk())
    names = [r.path.name for r in results]
    assert "small.txt" in names
    assert "big.bin" not in names


def test_scanner_records_mtime_and_size(tmp_path: Path):
    f = tmp_path / "a.txt"
    f.write_text("hello", encoding="utf-8")
    [rec] = list(Scanner(tmp_path).walk())
    assert rec.size == len("hello".encode("utf-8"))
    assert rec.mtime_ns > 0


def test_scanner_with_custom_ignore(tmp_path: Path):
    (tmp_path / "keep.txt").write_text("k", encoding="utf-8")
    (tmp_path / "drop.log").write_text("d", encoding="utf-8")
    matcher = IgnoreMatcher(tmp_path, extra_patterns=["*.log"])
    results = list(Scanner(tmp_path, ignore=matcher).walk())
    assert {r.path.name for r in results} == {"keep.txt"}


def test_scanner_honors_allowed_extensions(tmp_path: Path):
    (tmp_path / "keep.txt").write_text("k", encoding="utf-8")
    (tmp_path / "drop.md").write_text("d", encoding="utf-8")

    results = list(Scanner(tmp_path, allowed_exts={".txt"}).walk())

    assert [r.path.name for r in results] == ["keep.txt"]
