from pathlib import Path

from eoditdeora.collector.ignore import IgnoreMatcher


def test_default_patterns_ignore_vcs(tmp_path: Path):
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "HEAD").write_text("ref", encoding="utf-8")
    (tmp_path / "doc.txt").write_text("hi", encoding="utf-8")
    m = IgnoreMatcher(tmp_path)
    assert m.ignored(tmp_path / ".git" / "HEAD")
    assert not m.ignored(tmp_path / "doc.txt")


def test_user_ignore_file_is_respected(tmp_path: Path):
    (tmp_path / ".eoditdeora.ignore").write_text("secret/\n*.log\n", encoding="utf-8")
    (tmp_path / "secret").mkdir()
    (tmp_path / "secret" / "a.txt").write_text("s", encoding="utf-8")
    (tmp_path / "keep.txt").write_text("k", encoding="utf-8")
    (tmp_path / "keep.log").write_text("L", encoding="utf-8")
    m = IgnoreMatcher(tmp_path)
    assert m.ignored(tmp_path / "secret" / "a.txt")
    assert m.ignored(tmp_path / "keep.log")
    assert not m.ignored(tmp_path / "keep.txt")


def test_outside_root_not_ignored(tmp_path: Path):
    m = IgnoreMatcher(tmp_path)
    assert not m.ignored(Path("/nonexistent/elsewhere"))
