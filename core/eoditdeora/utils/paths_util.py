"""Cross-OS path helpers.

Windows and POSIX diverge in: separators, long-path handling, hidden-file
detection, and case-sensitivity. These helpers centralize the shims so
callers always work with POSIX-style `pathlib.Path` internally and only
flip to OS-native at the UI boundary.
"""

from __future__ import annotations

import os
import stat
import sys
from pathlib import Path, PureWindowsPath

_IS_WINDOWS = sys.platform == "win32"
_LONG_PATH_PREFIX = "\\\\?\\"


def normalize_path(path: str | os.PathLike[str]) -> Path:
    """Resolve to a canonical absolute path in POSIX style where possible.

    On Windows we strip the ``\\\\?\\`` long-path prefix if present but keep the
    drive letter. Path is returned as a `pathlib.Path` for downstream use.
    """
    p = Path(os.fspath(path))
    s = str(p)
    if _IS_WINDOWS and s.startswith(_LONG_PATH_PREFIX):
        s = s[len(_LONG_PATH_PREFIX):]
        p = Path(s)
    return p.expanduser().resolve()


def display_path(path: Path) -> str:
    """Return the path in the user's native style for UI display."""
    if _IS_WINDOWS:
        return str(PureWindowsPath(path))
    return str(path)


def path_is_hidden(path: Path) -> bool:
    name = path.name
    if name.startswith("."):
        return True
    if _IS_WINDOWS:
        try:
            attrs = path.stat().st_file_attributes  # type: ignore[attr-defined]
            return bool(attrs & stat.FILE_ATTRIBUTE_HIDDEN)  # type: ignore[attr-defined]
        except (AttributeError, OSError):
            return False
    return False


def safe_relative(path: Path, root: Path) -> Path | None:
    """Return `path` relative to `root` if inside, else None. Never throws."""
    try:
        return path.resolve().relative_to(root.resolve())
    except ValueError:
        return None


def apply_long_path_prefix(path: Path) -> Path:
    """On Windows, prefix with ``\\\\?\\`` so calls beyond MAX_PATH (260) work.

    No-op on POSIX.
    """
    if not _IS_WINDOWS:
        return path
    s = str(path)
    if s.startswith(_LONG_PATH_PREFIX):
        return path
    return Path(_LONG_PATH_PREFIX + s)
