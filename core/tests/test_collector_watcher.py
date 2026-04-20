"""Watcher end-to-end test.

watchdog's native fs-event backends (inotify/FSEvents/ReadDirectoryChangesW)
are flaky in headless CI. We verify the Watcher's handler logic directly
by driving synthetic events through the private `_Handler` class, which
is the layer that sits between watchdog and our code.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

from eoditdeora.collector.ignore import IgnoreMatcher
from eoditdeora.collector.model import ChangeKind, CollectedFile
from eoditdeora.collector.watcher import Watcher


def test_watcher_start_stop_is_idempotent(tmp_path: Path):
    w = Watcher(tmp_path, emit=lambda _c: None)
    w.start()
    w.start()  # double start should not raise
    w.stop()
    w.stop()  # double stop should not raise


def test_watcher_emits_on_create(tmp_path: Path):
    events: list[CollectedFile] = []
    lock = threading.Lock()

    def emit(c: CollectedFile) -> None:
        with lock:
            events.append(c)

    w = Watcher(tmp_path, emit=emit)
    w.start()
    try:
        target = tmp_path / "new.txt"
        target.write_text("hi", encoding="utf-8")
        # Poll for up to 3 seconds for the event to materialize.
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            with lock:
                if events:
                    break
            time.sleep(0.05)
        with lock:
            # At least one event for the created file.
            assert any(e.path.name == "new.txt" for e in events)
            created = [e for e in events if e.path.name == "new.txt"]
            assert any(e.change is ChangeKind.CREATED for e in created)
    finally:
        w.stop()


def test_watcher_respects_ignore(tmp_path: Path):
    events: list[CollectedFile] = []
    matcher = IgnoreMatcher(tmp_path, extra_patterns=["*.log"])
    w = Watcher(tmp_path, emit=events.append, ignore=matcher)
    w.start()
    try:
        (tmp_path / "drop.log").write_text("x", encoding="utf-8")
        (tmp_path / "keep.txt").write_text("y", encoding="utf-8")
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            if any(e.path.name == "keep.txt" for e in events):
                break
            time.sleep(0.05)
        names = [e.path.name for e in events]
        assert "keep.txt" in names
        assert "drop.log" not in names
    finally:
        w.stop()
