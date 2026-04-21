"""Bulk walker that populates `fast_index` from registered roots.

The heavy content indexer (`daemon.py`) walks each root once on launch
but spends most of its time parsing document bodies and calling the
embedding server. A user hitting file-name search in the first few
seconds can't wait for all that — they want Everything-style instant
results. This module provides a dedicated, parse-free walk that fills
`FastIndex` as quickly as the disk will go, independently of the
content pipeline.

Called from:
  * The RPC method `index.rescan` (after the user toggles extensions).
  * The indexer daemon's startup, in a background thread so content
    indexing doesn't block name-lookup availability.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import os
import queue
import time
from pathlib import Path
from typing import Any

from eoditdeora.collector.ignore import IgnoreMatcher
from eoditdeora.config import load_settings
from eoditdeora.storage.fast_index import FastIndex
from eoditdeora.utils.logging import get_logger

log = get_logger(__name__)

_BATCH = 500
_MAX_WORKERS = min(os.cpu_count() or 4, 8)
_SKIP_DIRS = {
    "node_modules",
    ".git",
    "__pycache__",
    "venv",
    ".venv",
    "dist",
    "build",
    ".cache",
    "target",
    "Library",
    "AppData",
}
_SUBROOT_DONE = object()


def _prune_dirnames(dirnames: list[str]) -> None:
    dirnames[:] = [
        d for d in dirnames if d not in _SKIP_DIRS and not d.startswith(".")
    ]


def _walk_subroot(
    subroot: Path,
    matcher: IgnoreMatcher,
    allowed_exts: set[str],
    max_bytes: int,
    outbox: queue.Queue[tuple[object, int, float]],
) -> None:
    seen = 0
    upserted = 0
    started = time.perf_counter()
    try:
        for dirpath, dirnames, filenames in os.walk(subroot, followlinks=False):
            _prune_dirnames(dirnames)
            for name in filenames:
                seen += 1
                ext = os.path.splitext(name)[1].lower()
                if allowed_exts and ext not in allowed_exts:
                    continue
                full = Path(dirpath) / name
                try:
                    if matcher.ignored(full):
                        continue
                    st = full.stat()
                except (PermissionError, FileNotFoundError, OSError):
                    continue
                if max_bytes and st.st_size > max_bytes:
                    continue
                outbox.put((str(full), st.st_size, st.st_mtime))
                upserted += 1
    finally:
        log.info(
            "fast_scan_subroot_done",
            subroot=str(subroot),
            seen=seen,
            upserted=upserted,
            ms=int((time.perf_counter() - started) * 1000),
        )
        outbox.put((_SUBROOT_DONE, seen, upserted))


def scan_root(root: Path, allowed_exts: set[str], max_bytes: int) -> tuple[int, int]:
    """Walk `root` once and upsert every matching file into the fast index.

    Returns (files_seen, files_upserted). `files_seen` counts entries
    the walker looked at, `files_upserted` counts rows actually touched.
    The difference is files filtered out by extension / size / ignore
    rules.
    """
    root = root.resolve()
    if not root.is_dir():
        return 0, 0
    return _scan_root_impl(root, allowed_exts, max_bytes, max_workers=_MAX_WORKERS)


def _scan_root_impl(
    root: Path,
    allowed_exts: set[str],
    max_bytes: int,
    *,
    max_workers: int,
) -> tuple[int, int]:
    matcher = IgnoreMatcher(root)
    fast = FastIndex()
    seen = 0
    upserted = 0
    batch: list[tuple[str, int, float]] = []
    outbox: queue.Queue[tuple[object, int, float]] = queue.Queue(maxsize=_BATCH * 4)
    subroots: list[Path] = []
    try:
        with os.scandir(root) as entries:
            for entry in entries:
                if entry.is_dir(follow_symlinks=False):
                    if entry.name not in _SKIP_DIRS and not entry.name.startswith("."):
                        subroots.append(Path(entry.path))
                    continue
                if not entry.is_file(follow_symlinks=False):
                    continue
                name = entry.name
                seen += 1
                ext = os.path.splitext(name)[1].lower()
                if allowed_exts and ext not in allowed_exts:
                    continue
                full = Path(entry.path)
                try:
                    if matcher.ignored(full):
                        continue
                    st = full.stat()
                except (PermissionError, FileNotFoundError, OSError):
                    continue
                if max_bytes and st.st_size > max_bytes:
                    continue
                batch.append((str(full), st.st_size, st.st_mtime))
                if len(batch) >= _BATCH:
                    upserted += fast.upsert_many(batch)
                    batch.clear()
        if max_workers <= 1:
            for subroot in subroots:
                _walk_subroot(subroot, matcher, allowed_exts, max_bytes, outbox)
                while True:
                    item = outbox.get()
                    if item[0] is _SUBROOT_DONE:
                        seen += int(item[1])
                        break
                    batch.append((str(item[0]), int(item[1]), float(item[2])))
                    if len(batch) >= _BATCH:
                        upserted += fast.upsert_many(batch)
                        batch.clear()
        else:
            with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
                futures = [
                    pool.submit(
                        _walk_subroot,
                        subroot,
                        matcher,
                        allowed_exts,
                        max_bytes,
                        outbox,
                    )
                    for subroot in subroots
                ]
                completed = 0
                while completed < len(futures):
                    item = outbox.get()
                    if item[0] is _SUBROOT_DONE:
                        seen += int(item[1])
                        completed += 1
                        continue
                    batch.append((str(item[0]), int(item[1]), float(item[2])))
                    if len(batch) >= _BATCH:
                        upserted += fast.upsert_many(batch)
                        batch.clear()
                for future in futures:
                    future.result()
        if batch:
            upserted += fast.upsert_many(batch)
    finally:
        fast.close()
    return seen, upserted


async def rescan_all() -> dict[str, Any]:
    """Fast-scan every registered root. Safe to call while the daemon
    is running — the fast_index uses WAL so concurrent writes are fine.
    """
    settings = load_settings()
    allowed_exts = {e.lower() for e in settings.index.extensions}

    loop = asyncio.get_running_loop()
    totals = {"roots": 0, "seen": 0, "upserted": 0}
    per_root: list[dict[str, Any]] = []
    for raw in settings.index.roots:
        root = Path(raw)
        if not root.is_dir():
            per_root.append({"root": raw, "error": "not_a_directory"})
            continue
        seen, up = await loop.run_in_executor(
            None,
            scan_root,
            root,
            allowed_exts,
            settings.index.max_file_bytes,
        )
        per_root.append({"root": str(root), "seen": seen, "upserted": up})
        totals["roots"] += 1
        totals["seen"] += seen
        totals["upserted"] += up
        log.info(
            "fast_index_rescan_done",
            root=str(root),
            seen=seen,
            upserted=up,
        )
    return {"totals": totals, "per_root": per_root}
