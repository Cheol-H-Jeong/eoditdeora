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
fast_index.db
fast_index.db-*
schema.sqlite3
schema.sqlite3-*
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
            resolved = path.resolve()
        except OSError:
            return True
        # Defense-in-depth: if the user's watched root is OUTSIDE our app
        # data directory, protect the app data from being crawled (e.g.
        # they added ~/home as a root — don't index ~/.local/share/eddr/).
        # If the root IS inside the app data dir (e.g. tests that use
        # tmp_path as both), trust the user and do not auto-protect.
        try:
            from eoditdeora.config.paths import get_paths

            app_root = get_paths().root.resolve()
            root_is_inside_app = (
                self._root == app_root or app_root in self._root.parents
            )
            if not root_is_inside_app:
                if resolved == app_root or app_root in resolved.parents:
                    return True
        except Exception:  # noqa: BLE001
            pass
        try:
            rel = resolved.relative_to(self._root)
        except ValueError:
            return False
        return self._spec.match_file(rel.as_posix())
