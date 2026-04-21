"""Live indexer daemon.

Wires the Collector (scanner + watcher) into the indexing pipeline so
that new/changed/deleted files land in the stores without any user
intervention. Lives inside the same process as the RPC server.

Flow:
  1. On start, for every registered root:
       * launch a Watcher (filesystem events → `_queue`)
       * enqueue a one-shot Scanner sweep to catch anything missed while
         the daemon was offline.
  2. A single background worker thread drains `_queue` and calls
     `index_file` for each event. Uses a dedicated MetaStore/FtsStore/
     VectorStore instance (thread-local).

This module is intentionally small: the pipeline itself does the real
work, and failure of one event never blocks another.
"""

from __future__ import annotations

import queue
import threading
import time
from pathlib import Path

from eoditdeora.collector.ignore import IgnoreMatcher
from eoditdeora.collector.model import ChangeKind, CollectedFile
from eoditdeora.collector.scanner import Scanner
from eoditdeora.collector.watcher import Watcher
from eoditdeora.config import load_settings
from eoditdeora.indexer.pipeline import index_file
from eoditdeora.storage.fts import FtsStore
from eoditdeora.storage.meta import MetaStore
from eoditdeora.storage.vectors import VectorStore
from eoditdeora.utils.logging import get_logger

log = get_logger(__name__)

_Q_MAX = 10_000


class IndexerDaemon:
    """Long-running indexer. Safe to `start()` once; `stop()` is idempotent."""

    def __init__(self) -> None:
        self._queue: "queue.Queue[CollectedFile | None]" = queue.Queue(maxsize=_Q_MAX)
        self._watchers: list[Watcher] = []
        self._worker_thread: threading.Thread | None = None
        self._running = False
        self._stats = {
            "indexed": 0,
            "skipped": 0,
            "deleted": 0,
            "errors": 0,
        }
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        with self._lock:
            if self._running:
                return
            self._running = True
            self._worker_thread = threading.Thread(
                target=self._run_worker, name="eddr-indexer", daemon=True
            )
            self._worker_thread.start()
            self._boot_roots()
            log.info("indexer_daemon_started", watchers=len(self._watchers))

    def stop(self) -> None:
        with self._lock:
            if not self._running:
                return
            self._running = False
            for w in self._watchers:
                try:
                    w.stop()
                except Exception as e:  # noqa: BLE001
                    log.debug("watcher_stop_error", error=str(e))
            self._watchers.clear()
            self._queue.put(None)  # wake worker
        if self._worker_thread is not None:
            self._worker_thread.join(timeout=5)
            self._worker_thread = None
        log.info("indexer_daemon_stopped")

    def refresh_roots(self) -> None:
        """Pick up newly-added roots without restarting the daemon."""
        self.stop()
        self.start()

    def stats(self) -> dict[str, int]:
        with self._lock:
            return dict(self._stats)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _boot_roots(self) -> None:
        settings = load_settings()
        for raw in settings.index.roots:
            root = Path(raw)
            if not root.is_dir():
                log.warning("root_missing", path=str(root))
                continue
            matcher = IgnoreMatcher(root)
            self._watchers.append(
                Watcher(
                    root=root,
                    emit=self._enqueue,
                    ignore=matcher,
                    max_bytes=settings.index.max_file_bytes,
                )
            )
            # Start the watcher BEFORE the catch-up scan so events that
            # fire during the scan are not lost.
            self._watchers[-1].start()
            # Schedule catch-up scan without blocking start().
            threading.Thread(
                target=self._catch_up_scan,
                args=(root, matcher, settings.index.max_file_bytes),
                name=f"eddr-scan:{root.name}",
                daemon=True,
            ).start()

    def _catch_up_scan(self, root: Path, matcher: IgnoreMatcher, max_bytes: int) -> None:
        scanner = Scanner(root, ignore=matcher, max_bytes=max_bytes)
        count = 0
        for rec in scanner.walk():
            self._enqueue(rec)
            count += 1
        log.info("catch_up_scan_done", root=str(root), files=count)

    def _enqueue(self, rec: CollectedFile) -> None:
        try:
            self._queue.put(rec, timeout=1.0)
        except queue.Full:
            log.warning("indexer_queue_full_dropping", path=str(rec.path))
            with self._lock:
                self._stats["skipped"] += 1

    def _run_worker(self) -> None:
        meta = MetaStore()
        fts = FtsStore()
        vectors = VectorStore()
        # Small debounce: collapse bursts of MODIFIED events on the same
        # path (editors often save in multiple fsync cycles).
        last_seen: dict[str, float] = {}
        try:
            while self._running:
                try:
                    item = self._queue.get(timeout=0.5)
                except queue.Empty:
                    continue
                if item is None:
                    break
                # Debounce MODIFIED within 400ms of the last event for
                # the same path.
                if item.change is ChangeKind.MODIFIED:
                    now = time.monotonic()
                    key = str(item.path)
                    if now - last_seen.get(key, 0) < 0.4:
                        continue
                    last_seen[key] = now
                try:
                    result = index_file(item, meta=meta, fts=fts, vectors=vectors)
                    with self._lock:
                        status = str(result.get("status", ""))
                        if status == "indexed":
                            self._stats["indexed"] += 1
                        elif status == "deleted":
                            self._stats["deleted"] += 1
                        else:
                            self._stats["skipped"] += 1
                except Exception as e:  # noqa: BLE001
                    log.exception("indexer_worker_error", path=str(item.path), error=str(e))
                    with self._lock:
                        self._stats["errors"] += 1
        finally:
            meta.close()


_singleton: IndexerDaemon | None = None
_singleton_lock = threading.Lock()


def get_daemon() -> IndexerDaemon:
    global _singleton
    with _singleton_lock:
        if _singleton is None:
            _singleton = IndexerDaemon()
    return _singleton
