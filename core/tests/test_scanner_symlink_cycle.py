from pathlib import Path

from eoditdeora.collector.scanner import Scanner


def test_scanner_walk_ignores_symlink_cycles(tmp_path: Path):
    docs = tmp_path / "docs"
    docs.mkdir()
    keep = docs / "keep.txt"
    keep.write_text("ok", encoding="utf-8")
    (docs / "loop").symlink_to(tmp_path, target_is_directory=True)

    results = list(Scanner(tmp_path).walk())

    assert [item.path for item in results] == [keep.resolve()]
