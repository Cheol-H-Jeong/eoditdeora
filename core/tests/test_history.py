from __future__ import annotations

import time
from pathlib import Path

from eoditdeora.storage.history import HistoryStore


def test_record_query_and_top_order(tmp_path: Path):
    store = HistoryStore(tmp_path / "history.sqlite3")
    try:
        store.record_query("alpha")
        time.sleep(0.01)
        store.record_query("beta")
        rows = store.top_queries()
        assert [row["query"] for row in rows] == ["beta", "alpha"]
    finally:
        store.close()


def test_duplicate_query_updates_count_and_timestamp(tmp_path: Path):
    store = HistoryStore(tmp_path / "history.sqlite3")
    try:
        store.record_query("alpha")
        first = store.top_queries(1)[0]
        time.sleep(0.01)
        store.record_query("alpha")
        updated = store.top_queries(1)[0]
        assert updated["count"] == 2
        assert updated["last_used_ts"] > first["last_used_ts"]
    finally:
        store.close()


def test_blank_query_is_ignored_and_trimmed(tmp_path: Path):
    store = HistoryStore(tmp_path / "history.sqlite3")
    try:
        store.record_query("   ")
        store.record_query("x" * 250)
        [row] = store.top_queries()
        assert row["query"] == "x" * 200
    finally:
        store.close()


def test_record_open_and_top_limit(tmp_path: Path):
    store = HistoryStore(tmp_path / "history.sqlite3")
    try:
        for idx in range(12):
            store.record_open(f"/tmp/file-{idx}.txt")
            time.sleep(0.002)
        rows = store.top_opens()
        assert len(rows) == 10
        assert rows[0]["path"] == "/tmp/file-11.txt"
        assert rows[-1]["path"] == "/tmp/file-2.txt"
    finally:
        store.close()


def test_duplicate_open_updates_count_and_timestamp(tmp_path: Path):
    store = HistoryStore(tmp_path / "history.sqlite3")
    try:
        store.record_open("/tmp/a.txt")
        first = store.top_opens(1)[0]
        time.sleep(0.01)
        store.record_open("/tmp/a.txt")
        updated = store.top_opens(1)[0]
        assert updated["count"] == 2
        assert updated["last_used_ts"] > first["last_used_ts"]
    finally:
        store.close()


def test_clear_removes_all_rows(tmp_path: Path):
    store = HistoryStore(tmp_path / "history.sqlite3")
    try:
        store.record_query("alpha")
        store.record_open("/tmp/a.txt")
        store.clear()
        assert store.top_queries() == []
        assert store.top_opens() == []
    finally:
        store.close()
