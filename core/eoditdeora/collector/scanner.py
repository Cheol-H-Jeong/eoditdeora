"""One-shot recursive scan used for initial indexing and for periodic
reconciliation (in case filesystem events are missed).
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from eoditdeora.collector.ignore import IgnoreMatcher
from eoditdeora.collector.model import ChangeKind, CollectedFile
from eoditdeora.utils.logging import get_logger

log = get_logger(__name__)


class Scanner:
    def __init__(
        self,
        root: Path,
        ignore: IgnoreMatcher | None = None,
        max_bytes: int = 256 * 1024 * 1024,
    ) -> None:
        self._root = root.resolve()
        self._ignore = ignore or IgnoreMatcher(self._root)
        self._max_bytes = max_bytes

    def walk(self) -> Iterator[CollectedFile]:
        """Yield one record per file. Always uses CREATED; the indexer
        decides what is actually new by comparing against its own state.
        """
        for p in self._root.rglob("*"):
            if self._ignore.ignored(p):
                continue
            try:
                if not p.is_file():
                    continue
                st = p.stat()
            except (PermissionError, FileNotFoundError, OSError) as e:
                log.debug("scan_stat_failed", path=str(p), error=str(e))
                continue
            if st.st_size > self._max_bytes:
                log.debug("scan_skipped_too_large", path=str(p), size=st.st_size)
                continue
            yield CollectedFile(
                path=p.resolve(),
                root=self._root,
                size=st.st_size,
                mtime_ns=st.st_mtime_ns,
                change=ChangeKind.CREATED,
            )
