"""gitignore-style match using `pathspec`.

A root can have its own `.eoditdeora.ignore`. Global defaults are merged
in from the `Settings.index.ignore_patterns` list. Matching is relative to
the root, consistent with gitignore.
"""

from __future__ import annotations

from pathlib import Path

import pathspec

_DEFAULTS = """
# Eoditdeora defaults
.git/
.svn/
.hg/
.DS_Store
Thumbs.db
desktop.ini
__pycache__/
node_modules/
.venv/
venv/
dist/
build/
target/
~$*
*.tmp
*.bak
*.swp
$RECYCLE.BIN/
.Trash*/
.eoditdeora.local/
"""


class IgnoreMatcher:
    def __init__(
        self,
        root: Path,
        extra_patterns: list[str] | None = None,
        ignore_file: str = ".eoditdeora.ignore",
    ) -> None:
        self._root = root.resolve()
        patterns: list[str] = _DEFAULTS.splitlines()
        if extra_patterns:
            patterns.extend(extra_patterns)
        f = self._root / ignore_file
        if f.exists():
            try:
                patterns.extend(f.read_text(encoding="utf-8").splitlines())
            except OSError:
                pass
        self._spec = pathspec.PathSpec.from_lines("gitignore", patterns)

    def ignored(self, path: Path) -> bool:
        try:
            rel = path.resolve().relative_to(self._root)
        except ValueError:
            return False
        return self._spec.match_file(rel.as_posix())
