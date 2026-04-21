from pathlib import Path

from watchdog.events import FileMovedEvent

from eoditdeora.collector.ignore import IgnoreMatcher
from eoditdeora.collector.model import ChangeKind, CollectedFile
from eoditdeora.collector.watcher import _Handler


def test_handler_emits_atomic_move_event(tmp_path: Path):
    src = tmp_path / "before.txt"
    dst = tmp_path / "after.txt"
    src.write_text("payload", encoding="utf-8")
    src.rename(dst)

    events: list[CollectedFile] = []
    handler = _Handler(
        tmp_path.resolve(),
        IgnoreMatcher(tmp_path),
        events.append,
        max_bytes=1024,
    )

    handler.on_moved(FileMovedEvent(str(src), str(dst)))

    assert len(events) == 1
    event = events[0]
    assert event.change is ChangeKind.MOVED
    assert event.previous_path == src.resolve()
    assert event.path == dst.resolve()
    assert event.size == len("payload".encode("utf-8"))


def test_handler_turns_move_to_disallowed_extension_into_delete(tmp_path: Path):
    src = tmp_path / "before.txt"
    dst = tmp_path / "after.bin"
    src.write_text("payload", encoding="utf-8")
    src.rename(dst)

    events: list[CollectedFile] = []
    handler = _Handler(
        tmp_path.resolve(),
        IgnoreMatcher(tmp_path),
        events.append,
        max_bytes=1024,
        allowed_exts={".txt"},
    )

    handler.on_moved(FileMovedEvent(str(src), str(dst)))

    assert len(events) == 1
    event = events[0]
    assert event.change is ChangeKind.DELETED
    assert event.path == src.resolve()
