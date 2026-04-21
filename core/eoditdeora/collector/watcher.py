"""Long-running filesystem watcher.

Uses watchdog so Linux (inotify) and Windows (ReadDirectoryChangesW) are
covered by the same code. Watchdog's abstraction does not always report
moves as moves on Windows — we compensate by falling back to
DELETED + CREATED pairs when a MOVED event isn't emitted.

The watcher emits records via a callback rather than returning an
iterator, because filesystem events arrive from a dedicated thread and
we want the indexer to backpressure on its own queue.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path

from watchdog.events import (  # type: ignore[import-untyped]
    FileCreatedEvent,
    FileDeletedEvent,
    FileModifiedEvent,
    FileMovedEvent,
    FileSystemEvent,
    FileSystemEventHandler,
)
from watchdog.observers import Observer  # type: ignore[import-untyped]

from eoditdeora.collector.ignore import IgnoreMatcher
from eoditdeora.collector.model import ChangeKind, CollectedFile
from eoditdeora.utils.logging import get_logger

log = get_logger(__name__)


class _Handler(FileSystemEventHandler):
    def __init__(
        self,
        root: Path,
        ignore: IgnoreMatcher,
        emit: Callable[[CollectedFile], None],
        max_bytes: int,
    ) -> None:
        self._root = root
        self._ignore = ignore
        self._emit = emit
        self._max_bytes = max_bytes

    def _within_root(self, path: Path) -> bool:
        try:
            path.resolve().relative_to(self._root)
        except ValueError:
            return False
        except OSError:
            return False
        return True

    def _accept(self, path: Path) -> bool:
        if not self._within_root(path):
            return False
        if self._ignore.ignored(path):
            return False
        return True

    def _stat_emit(self, path: Path, change: ChangeKind, previous: Path | None = None) -> None:
        try:
            st = path.stat() if change is not ChangeKind.DELETED else None
        except (PermissionError, FileNotFoundError, OSError):
            return
        size = st.st_size if st else 0
        mtime_ns = st.st_mtime_ns if st else 0
        if st and size > self._max_bytes:
            return
        self._emit(
            CollectedFile(
                path=path.resolve(),
                root=self._root,
                size=size,
                mtime_ns=mtime_ns,
                change=change,
                previous_path=previous.resolve() if previous else None,
            )
        )

    def on_created(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        p = Path(event.src_path)
        if not self._accept(p):
            return
        self._stat_emit(p, ChangeKind.CREATED)

    def on_modified(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        p = Path(event.src_path)
        if not self._accept(p):
            return
        self._stat_emit(p, ChangeKind.MODIFIED)

    def on_deleted(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        p = Path(event.src_path)
        if not self._accept(p):
            return
        self._stat_emit(p, ChangeKind.DELETED)

    def on_moved(self, event: FileSystemEvent) -> None:
        """Emit a single MOVED record when both endpoints stay in-root.

        The indexing pipeline applies `previous_path` via `meta.replace_path`
        so doc_id stays stable across a rename.
        """
        if event.is_directory:
            return
        src = Path(event.src_path)
        dst = Path(getattr(event, "dest_path", event.src_path))
        src_ok = self._accept(src)
        dst_ok = self._accept(dst)
        if src_ok and dst_ok:
            self._stat_emit(dst, ChangeKind.MOVED, previous=src)
            return
        if src_ok:
            self._stat_emit(src, ChangeKind.DELETED)
            return
        if not dst_ok:
            return
        self._stat_emit(dst, ChangeKind.CREATED)


class Watcher:
    def __init__(
        self,
        root: Path,
        emit: Callable[[CollectedFile], None],
        ignore: IgnoreMatcher | None = None,
        max_bytes: int = 256 * 1024 * 1024,
    ) -> None:
        self._root = root.resolve()
        self._emit = emit
        self._ignore = ignore or IgnoreMatcher(self._root)
        self._observer: Observer | None = None
        self._lock = threading.Lock()
        self._max_bytes = max_bytes

    def start(self) -> None:
        with self._lock:
            if self._observer is not None:
                return
            obs = Observer()
            obs.schedule(
                _Handler(self._root, self._ignore, self._emit, self._max_bytes),
                str(self._root),
                recursive=True,
            )
            obs.start()
            self._observer = obs
            log.info("watcher_started", root=str(self._root))

    def stop(self) -> None:
        with self._lock:
            if self._observer is None:
                return
            self._observer.stop()
            self._observer.join(timeout=5)
            self._observer = None
            log.info("watcher_stopped", root=str(self._root))
