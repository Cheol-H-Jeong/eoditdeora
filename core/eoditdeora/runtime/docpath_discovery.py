"""Well-known document folder discovery.

The first-run bootstrap used to add only `~/Documents`, which missed the
places most Korean office users actually keep their files: the desktop,
Downloads, OneDrive sync folders, and the localized Korean names
(`문서`, `바탕화면`, `내려받기`). This module enumerates every plausible
document root for the current platform, checks which ones exist, and
classifies them as "has_documents" (contains at least one indexable file
somewhere in its tree) so the caller can pick a sensible default set of
roots without forcing the user to type paths.

Discovery is cheap but not free — we walk at most `MAX_SCAN_FILES` and
`MAX_SCAN_DEPTH` per candidate to keep the first-launch latency bounded
on slow disks. If a folder is huge, the walk short-circuits as soon as
*any* matching file is seen.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from eoditdeora.utils.logging import get_logger

log = get_logger(__name__)


# Extensions the indexer can actually parse today. Keeping this list in
# sync with `collector.scanner.SUPPORTED_EXTENSIONS` is the user's
# responsibility; duplicating the constant here keeps this module free
# of import cycles with the collector.
DEFAULT_DOC_EXTS: frozenset[str] = frozenset(
    {
        ".hwp", ".hwpx",
        ".pdf",
        ".doc", ".docx",
        ".ppt", ".pptx",
        ".xls", ".xlsx",
        ".txt", ".md", ".markdown",
        ".rtf", ".odt", ".ods", ".odp",
    }
)

# Cap per-candidate walk so /home on a spinning disk doesn't stall the
# launcher. Good enough to decide "has documents" vs "empty".
MAX_SCAN_FILES = 20_000
MAX_SCAN_DEPTH = 6


@dataclass(frozen=True)
class DocRoot:
    path: str
    display_name: str
    exists: bool
    has_documents: bool
    sample_count: int  # files we saw before short-circuiting

    def to_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "display_name": self.display_name,
            "exists": self.exists,
            "has_documents": self.has_documents,
            "sample_count": self.sample_count,
        }


def candidate_paths() -> list[tuple[str, Path]]:
    """Ordered list of `(display_name, path)` candidates for this platform.

    Paths that don't exist are still returned; callers decide what to
    do with them (typically: drop). The display name is what the UI
    shows so non-English paths like `C:\\Users\\x\\OneDrive\\문서` get a
    friendly label rather than raw path text.
    """
    home = Path.home()
    candidates: list[tuple[str, Path]] = []

    if sys.platform == "win32":
        userprofile = Path(os.environ.get("USERPROFILE", str(home)))
        candidates += [
            ("Documents", userprofile / "Documents"),
            ("Desktop", userprofile / "Desktop"),
            ("Downloads", userprofile / "Downloads"),
            ("내 문서", userprofile / "문서"),
            ("바탕 화면", userprofile / "바탕 화면"),
            ("바탕화면", userprofile / "바탕화면"),
            ("다운로드", userprofile / "다운로드"),
            ("내려받기", userprofile / "내려받기"),
        ]
        # OneDrive (Personal + Business). OneDrive sets env vars when
        # installed; fall back to the default names if not. Korean
        # Windows localizes every standard folder — bare `Documents`
        # without `문서/바탕 화면/다운로드/내려받기` would miss the
        # majority of files on a ko-KR locale install.
        onedrive_subfolders = (
            ("Documents", "Documents"),
            ("문서", "문서"),
            ("Desktop", "Desktop"),
            ("바탕 화면", "바탕 화면"),
            ("바탕화면", "바탕화면"),
            ("Downloads", "Downloads"),
            ("다운로드", "다운로드"),
            ("내려받기", "내려받기"),
        )
        for env in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial"):
            v = os.environ.get(env)
            if v:
                p = Path(v)
                candidates.append((env, p))
                for label, sub in onedrive_subfolders:
                    candidates.append((f"{env}/{label}", p / sub))
        for guess in ("OneDrive", "OneDrive - Personal"):
            p = userprofile / guess
            candidates.append((guess, p))
            for label, sub in onedrive_subfolders:
                candidates.append((f"{guess}/{label}", p / sub))
        # Hancom default library (한컴오피스).
        candidates.append(("한컴오피스 문서", userprofile / "Documents" / "Hancom"))
        candidates.append(("HncDownload", userprofile / "HncDownload"))
    elif sys.platform == "darwin":
        candidates += [
            ("Documents", home / "Documents"),
            ("Desktop", home / "Desktop"),
            ("Downloads", home / "Downloads"),
        ]
        icloud = home / "Library" / "Mobile Documents" / "com~apple~CloudDocs"
        candidates.append(("iCloud Drive", icloud))
        candidates.append(("iCloud/문서", icloud / "문서"))
    else:  # Linux / BSD
        candidates += [
            ("Documents", home / "Documents"),
            ("문서", home / "문서"),
            ("Desktop", home / "Desktop"),
            ("바탕화면", home / "바탕화면"),
            ("Downloads", home / "Downloads"),
            ("내려받기", home / "내려받기"),
        ]
        # XDG override if set.
        xdg_docs = os.environ.get("XDG_DOCUMENTS_DIR")
        if xdg_docs:
            candidates.append(("XDG Documents", Path(xdg_docs)))
        xdg_dl = os.environ.get("XDG_DOWNLOAD_DIR")
        if xdg_dl:
            candidates.append(("XDG Downloads", Path(xdg_dl)))

    # Deduplicate while preserving order — later entries with the same
    # path lose to earlier ones so the friendliest display name wins.
    seen: set[Path] = set()
    out: list[tuple[str, Path]] = []
    for label, p in candidates:
        try:
            resolved = p.expanduser().resolve()
        except Exception:  # noqa: BLE001
            continue
        if resolved in seen:
            continue
        seen.add(resolved)
        out.append((label, resolved))
    return out


def _has_docs(root: Path, exts: frozenset[str]) -> tuple[bool, int]:
    """Walk until we hit a document or run out of budget.

    Returns (has_any, files_seen). Keeps the walk bounded so first-run
    latency is predictable even on slow disks.
    """
    if not root.exists() or not root.is_dir():
        return False, 0
    seen = 0
    try:
        for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
            depth = len(Path(dirpath).relative_to(root).parts)
            if depth >= MAX_SCAN_DEPTH:
                dirnames[:] = []  # don't descend further
            # Skip common heavyweight directories that are never
            # user-owned documents.
            dirnames[:] = [
                d for d in dirnames
                if d not in {
                    "node_modules", ".git", "__pycache__", "venv",
                    ".venv", "dist", "build", ".cache", "target",
                    "Library", "AppData",
                }
                and not d.startswith(".")
            ]
            for name in filenames:
                seen += 1
                if seen > MAX_SCAN_FILES:
                    return False, seen
                ext = os.path.splitext(name)[1].lower()
                if ext in exts:
                    return True, seen
    except (PermissionError, OSError) as e:
        log.debug("docpath_scan_failed", path=str(root), error=str(e))
    return False, seen


def discover(
    exts: Iterable[str] | None = None,
) -> list[DocRoot]:
    """Probe every candidate and return what we found.

    Folders that exist but look empty of indexable documents are still
    returned (with `has_documents=False`) so the UI can offer them as
    opt-in additions.
    """
    extset = frozenset(e.lower() for e in (exts or DEFAULT_DOC_EXTS))
    out: list[DocRoot] = []
    for label, path in candidate_paths():
        exists = path.exists() and path.is_dir()
        if not exists:
            out.append(
                DocRoot(
                    path=str(path),
                    display_name=label,
                    exists=False,
                    has_documents=False,
                    sample_count=0,
                )
            )
            continue
        has_any, count = _has_docs(path, extset)
        out.append(
            DocRoot(
                path=str(path),
                display_name=label,
                exists=True,
                has_documents=has_any,
                sample_count=count,
            )
        )
    return out


_ALWAYS_ADD_BASENAMES = frozenset({"Documents", "문서", "내 문서"})


def default_roots() -> list[str]:
    """The subset of discovered paths we auto-add on first run.

    Rule: a path must exist AND either
      * contain at least one indexable document (caught real work), or
      * be the canonical `Documents` / `문서` folder (the user will
        put files there later, and we want to be watching when they do).

    Other candidates (Desktop, Downloads, OneDrive, ...) only qualify
    when they already hold documents — otherwise we'd flood the
    watchdog with noise from empty system folders.
    """
    out: list[str] = []
    for r in discover():
        if not r.exists:
            continue
        if r.has_documents:
            out.append(r.path)
            continue
        basename = os.path.basename(r.path.rstrip(os.sep))
        if basename in _ALWAYS_ADD_BASENAMES:
            out.append(r.path)
    return out
