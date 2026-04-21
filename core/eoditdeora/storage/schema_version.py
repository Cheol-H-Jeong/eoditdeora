from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from pathlib import Path

from eoditdeora.utils.logging import get_logger

log = get_logger(__name__)

CURRENT_SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_versions (
    store_name   TEXT PRIMARY KEY,
    version      INTEGER NOT NULL,
    migrated_at  REAL NOT NULL
)
"""


class SchemaVersionStore:
    def __init__(self, index_dir: Path) -> None:
        self._path = index_dir / "schema.sqlite3"
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._path), check_same_thread=False)
        with self._conn:
            self._conn.executescript(_SCHEMA)

    @property
    def path(self) -> Path:
        return self._path

    def get_version(self, store_name: str) -> int | None:
        cur = self._conn.execute(
            "SELECT version FROM schema_versions WHERE store_name = ?",
            (store_name,),
        )
        row = cur.fetchone()
        return None if row is None else int(row[0])

    def set_version(self, store_name: str, version: int) -> None:
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO schema_versions (store_name, version, migrated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(store_name) DO UPDATE SET
                    version = excluded.version,
                    migrated_at = excluded.migrated_at
                """,
                (store_name, int(version), time.time()),
            )

    def ensure_version(
        self,
        store_name: str,
        expected: int,
        rebuild_callback: Callable[[], None],
    ) -> None:
        current = self.get_version(store_name)
        if current is None:
            self.set_version(store_name, expected)
            return
        if current == expected:
            return
        log.info(
            "schema_rebuild",
            store=store_name,
            old_version=current,
            new_version=expected,
        )
        rebuild_callback()
        self.set_version(store_name, expected)

    def close(self) -> None:
        self._conn.close()


def get_version(index_dir: Path, store_name: str) -> int | None:
    store = SchemaVersionStore(index_dir)
    try:
        return store.get_version(store_name)
    finally:
        store.close()


def set_version(index_dir: Path, store_name: str, version: int) -> None:
    store = SchemaVersionStore(index_dir)
    try:
        store.set_version(store_name, version)
    finally:
        store.close()


def ensure_version(
    index_dir: Path,
    store_name: str,
    expected: int,
    rebuild_callback: Callable[[], None],
) -> None:
    store = SchemaVersionStore(index_dir)
    try:
        store.ensure_version(store_name, expected, rebuild_callback)
    finally:
        store.close()
