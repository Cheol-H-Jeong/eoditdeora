from __future__ import annotations

import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from eoditdeora.config.paths import get_paths
from eoditdeora.storage.schema_version import ensure_version

HISTORY_SCHEMA_VERSION = 1
_MAX_QUERY_LEN = 200
_MAX_PATH_LEN = 4096

_SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;

CREATE TABLE IF NOT EXISTS recent_queries (
    query         TEXT PRIMARY KEY,
    last_used_ts  REAL NOT NULL,
    count         INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS recent_opens (
    path          TEXT PRIMARY KEY,
    last_used_ts  REAL NOT NULL,
    count         INTEGER NOT NULL DEFAULT 1
);
"""


class HistoryStore:
    def __init__(self, db_path: Path | None = None) -> None:
        self._path = db_path or (get_paths().index / "history.sqlite3")
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        ensure_version(
            self._path.parent,
            "history",
            HISTORY_SCHEMA_VERSION,
            self._rebuild_schema,
        )
        self._init_schema()

    @property
    def path(self) -> Path:
        return self._path

    @contextmanager
    def tx(self):  # type: ignore[no-untyped-def]
        cur = self._conn.cursor()
        try:
            yield cur
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise
        finally:
            cur.close()

    def _init_schema(self) -> None:
        with self._conn:
            self._conn.executescript(_SCHEMA)

    def _rebuild_schema(self) -> None:
        with self._conn:
            self._conn.executescript(
                """
                DROP TABLE IF EXISTS recent_queries;
                DROP TABLE IF EXISTS recent_opens;
                """
            )
        self._init_schema()

    def record_query(self, query: str) -> None:
        normalized = query.strip()[:_MAX_QUERY_LEN]
        if not normalized:
            return
        self._upsert_recent(
            table="recent_queries",
            column="query",
            value=normalized,
        )

    def record_open(self, path: str) -> None:
        normalized = path[:_MAX_PATH_LEN]
        if not normalized.strip():
            return
        self._upsert_recent(
            table="recent_opens",
            column="path",
            value=normalized,
        )

    def top_queries(self, n: int = 5) -> list[dict[str, Any]]:
        limit = max(0, int(n))
        cur = self._conn.execute(
            """
            SELECT query, last_used_ts, count
            FROM recent_queries
            ORDER BY last_used_ts DESC
            LIMIT ?
            """,
            (limit,),
        )
        return [dict(row) for row in cur.fetchall()]

    def top_opens(self, n: int = 10) -> list[dict[str, Any]]:
        limit = max(0, int(n))
        cur = self._conn.execute(
            """
            SELECT path, last_used_ts, count
            FROM recent_opens
            ORDER BY last_used_ts DESC
            LIMIT ?
            """,
            (limit,),
        )
        return [dict(row) for row in cur.fetchall()]

    def clear(self) -> None:
        with self.tx() as cur:
            cur.execute("DELETE FROM recent_queries")
            cur.execute("DELETE FROM recent_opens")

    def close(self) -> None:
        self._conn.close()

    def _upsert_recent(self, *, table: str, column: str, value: str) -> None:
        now = time.time()
        with self.tx() as cur:
            cur.execute(
                f"""
                INSERT INTO {table} ({column}, last_used_ts, count)
                VALUES (?, ?, 1)
                ON CONFLICT({column}) DO UPDATE SET
                    last_used_ts = excluded.last_used_ts,
                    count = {table}.count + 1
                """,
                (value, now),
            )
