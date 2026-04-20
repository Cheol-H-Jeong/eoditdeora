from pathlib import Path

from eoditdeora.utils.paths_util import (
    apply_long_path_prefix,
    display_path,
    normalize_path,
    path_is_hidden,
    safe_relative,
)


def test_normalize_path_resolves_home(tmp_path: Path, monkeypatch):
    # A non-existent path with tilde is expanded.
    monkeypatch.setenv("HOME", str(tmp_path))
    p = normalize_path("~/thing")
    assert str(p).startswith(str(tmp_path))


def test_display_path_returns_string(tmp_path: Path):
    p = tmp_path / "x.txt"
    p.write_text("x", encoding="utf-8")
    s = display_path(p)
    assert isinstance(s, str)
    assert "x.txt" in s


def test_hidden_detection_unix(tmp_path: Path):
    dotted = tmp_path / ".hidden"
    dotted.write_text("x", encoding="utf-8")
    visible = tmp_path / "visible"
    visible.write_text("x", encoding="utf-8")
    assert path_is_hidden(dotted) is True
    assert path_is_hidden(visible) is False


def test_safe_relative(tmp_path: Path):
    inside = tmp_path / "a" / "b.txt"
    inside.parent.mkdir()
    inside.write_text("x", encoding="utf-8")
    rel = safe_relative(inside, tmp_path)
    assert rel == Path("a/b.txt")
    assert safe_relative(Path("/does/not/belong"), tmp_path) is None


def test_long_path_prefix_is_noop_on_unix(tmp_path: Path):
    # On Linux/macOS the helper should not prepend anything.
    result = apply_long_path_prefix(tmp_path)
    assert str(result) == str(tmp_path)
