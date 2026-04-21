"""Everything-tier file-name index.

Keeps a flat SQLite table `(path, name, parent, size, mtime, ext)`
mirrored by an FTS5 virtual table using the `trigram` tokenizer. A
trigram index lets the UI match arbitrary substrings (e.g. `eport`
matches `2025-1Q_report.hwpx`) at sub-50ms on hundreds of thousands of
rows, which is the baseline Korean office users expect coming from
Everything / Listary / fd on Windows.

This store is intentionally independent from the heavy content pipeline
(`fts.py`, `vectors.py`). A filename lookup must succeed even when the
LanceDB table is empty, the LLM endpoint is misconfigured, or the
embedder has never been reached. The only thing this index needs is the
filesystem.
"""

from __future__ import annotations

import os
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from eoditdeora.config.paths import get_paths
from eoditdeora.storage.schema_version import CURRENT_SCHEMA_VERSION, ensure_version
from eoditdeora.utils.query_terms import expand_search_terms
from eoditdeora.utils.logging import get_logger

log = get_logger(__name__)


DB_NAME = "fast_index.db"

_SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA temp_store = MEMORY;

CREATE TABLE IF NOT EXISTS files (
    path   TEXT PRIMARY KEY,
    name   TEXT NOT NULL,
    parent TEXT NOT NULL,
    size   INTEGER NOT NULL,
    mtime  REAL NOT NULL,
    ext    TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_files_ext ON files(ext);
CREATE INDEX IF NOT EXISTS idx_files_parent ON files(parent);

-- External-content FTS keeps the payload in `files` and only the search
-- columns in the virtual table. Keeps DB size under control (trigram
-- indexes are big) and guarantees consistency via triggers below.
CREATE VIRTUAL TABLE IF NOT EXISTS files_fts USING fts5(
    name, parent, path,
    content='files', content_rowid='rowid',
    tokenize='trigram'
);

CREATE TRIGGER IF NOT EXISTS files_ai AFTER INSERT ON files BEGIN
  INSERT INTO files_fts(rowid, name, parent, path)
    VALUES (new.rowid, new.name, new.parent, new.path);
END;

CREATE TRIGGER IF NOT EXISTS files_ad AFTER DELETE ON files BEGIN
  INSERT INTO files_fts(files_fts, rowid, name, parent, path)
    VALUES ('delete', old.rowid, old.name, old.parent, old.path);
END;

CREATE TRIGGER IF NOT EXISTS files_au AFTER UPDATE ON files BEGIN
  INSERT INTO files_fts(files_fts, rowid, name, parent, path)
    VALUES ('delete', old.rowid, old.name, old.parent, old.path);
  INSERT INTO files_fts(rowid, name, parent, path)
    VALUES (new.rowid, new.name, new.parent, new.path);
END;
"""


@dataclass(frozen=True)
class FastRow:
    path: str
    name: str
    parent: str
    size: int
    mtime: float
    ext: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "name": self.name,
            "parent": self.parent,
            "size": self.size,
            "mtime": self.mtime,
            "ext": self.ext,
        }


# Process-wide writer lock, keyed by DB path. The daemon worker keeps
# one FastIndex alive for hours while background rescans / watchdog
# events open short-lived ones — each instance would get its own
# threading.Lock if we stored it on the instance, which wouldn't
# actually serialize writes across instances. We key by db_path so
# tests using temp DBs don't block each other while the production
# instance's writes stay strictly ordered.
_WRITE_LOCKS: dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


def _lock_for(path: Path) -> threading.Lock:
    key = str(path.resolve())
    with _LOCKS_GUARD:
        lock = _WRITE_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _WRITE_LOCKS[key] = lock
        return lock


def _root_like_pattern(root: Path | str) -> str:
    p = str(Path(root)).rstrip(os.sep) + os.sep
    return p.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


class FastIndex:
    """Thread-safe file-name index.

    Writer serialization spans the whole process (not just this
    instance) because the daemon worker, on-demand rescan, and watchdog
    events each construct their own `FastIndex`. Keying the lock on
    the DB path guarantees that concurrent instances still write in
    strict order and do not race on SQLite's single-writer WAL model.

    SQLite itself is also told to wait up to `busy_timeout` ms on
    contention instead of returning `database is locked` immediately —
    cheap insurance on Windows, where the OS sometimes briefly holds
    the WAL file open during antivirus scans.
    """

    _BUSY_TIMEOUT_MS = 5000

    def __init__(self, db_path: Path | None = None) -> None:
        self._path = db_path or (get_paths().index / DB_NAME)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = _lock_for(self._path)
        self._conn = sqlite3.connect(
            str(self._path), check_same_thread=False, isolation_level=None
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute(f"PRAGMA busy_timeout = {self._BUSY_TIMEOUT_MS}")
        ensure_version(
            self._path.parent,
            "fast_index",
            CURRENT_SCHEMA_VERSION,
            self._rebuild_schema,
        )
        with self._lock:
            self._conn.executescript(_SCHEMA)

    def _rebuild_schema(self) -> None:
        with self._lock:
            with self._conn:
                self._conn.executescript(
                    """
                    DROP TABLE IF EXISTS files_fts;
                    DROP TABLE IF EXISTS files;
                    """
                )
            self._conn.executescript(_SCHEMA)

    # ------------------------------------------------------------------
    # Mutation
    # ------------------------------------------------------------------

    def upsert(self, path: Path | str, size: int, mtime: float) -> None:
        p = str(Path(path))
        name = os.path.basename(p)
        parent = os.path.dirname(p)
        ext = os.path.splitext(name)[1].lower()
        with self._lock:
            self._conn.execute(
                "INSERT INTO files(path, name, parent, size, mtime, ext) "
                "VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(path) DO UPDATE SET "
                "  name=excluded.name, parent=excluded.parent, "
                "  size=excluded.size, mtime=excluded.mtime, ext=excluded.ext",
                (p, name, parent, int(size), float(mtime), ext),
            )

    def upsert_many(self, rows: list[tuple[str, int, float]]) -> int:
        """Bulk upsert. `rows` is a list of (path, size, mtime).

        Returns the number of rows actually written. Used by the initial
        walker to amortize the WAL flush cost — SQLite on Windows is
        painfully slow at one-by-one inserts with autocommit.
        """
        if not rows:
            return 0
        payload = []
        for path, size, mtime in rows:
            p = str(Path(path))
            name = os.path.basename(p)
            parent = os.path.dirname(p)
            ext = os.path.splitext(name)[1].lower()
            payload.append((p, name, parent, int(size), float(mtime), ext))
        with self._lock:
            with self._conn:
                self._conn.executemany(
                    "INSERT INTO files(path, name, parent, size, mtime, ext) "
                    "VALUES (?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(path) DO UPDATE SET "
                    "  name=excluded.name, parent=excluded.parent, "
                    "  size=excluded.size, mtime=excluded.mtime, ext=excluded.ext",
                    payload,
                )
        return len(payload)

    def delete(self, path: Path | str) -> None:
        p = str(Path(path))
        with self._lock:
            self._conn.execute("DELETE FROM files WHERE path = ?", (p,))

    def delete_under(self, root: Path | str) -> int:
        """Drop every row whose path starts with `root`.

        Used when the user removes an index root so the fast index
        stops advertising paths we're no longer watching. All three
        LIKE metacharacters (`%`, `_`, `\\`) are escaped; forgetting
        `_` was a real bug because e.g. `/home/x/my_docs` would have
        matched `/home/x/myAdocs` too and deleted unrelated rows.
        """
        like_pattern = _root_like_pattern(root)
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM files WHERE path LIKE ? ESCAPE '\\'",
                (like_pattern,),
            )
            return int(cur.rowcount or 0)

    def delete_missing_under(self, root: Path | str, keep_paths: set[str]) -> int:
        """Drop rows under `root` that were not seen during a rescan.

        The fast scan mirrors the current filesystem into this store.
        Without the stale-row purge, deleting a file outside the app and
        hitting "rescan" would keep surfacing the removed path forever.
        """
        if not keep_paths:
            return self.delete_under(root)

        like_pattern = _root_like_pattern(root)
        with self._lock:
            with self._conn:
                self._conn.execute(
                    "CREATE TEMP TABLE IF NOT EXISTS keep_paths(path TEXT PRIMARY KEY)"
                )
                self._conn.execute("DELETE FROM keep_paths")
                self._conn.executemany(
                    "INSERT INTO keep_paths(path) VALUES (?)",
                    ((path,) for path in sorted(keep_paths)),
                )
                cur = self._conn.execute(
                    "DELETE FROM files "
                    "WHERE path LIKE ? ESCAPE '\\' "
                    "  AND path NOT IN (SELECT path FROM keep_paths)",
                    (like_pattern,),
                )
                deleted = int(cur.rowcount or 0)
                self._conn.execute("DELETE FROM keep_paths")
                return deleted

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def search(
        self,
        query: str,
        *,
        limit: int = 50,
        exts: list[str] | None = None,
    ) -> list[FastRow]:
        """Return path matches ordered by FTS rank (or recency for
        short queries).

        SQLite's trigram tokenizer requires the query to contain at
        least one trigram, i.e. ≥3 chars. When the user types 1 or 2
        characters (very common in Korean — a single-syllable noun is
        one ASCII-width char) we fall back to a LIKE scan over the
        filename and path columns. This keeps the short-query behavior
        aligned with the trigram path search so two-syllable folder
        names still surface immediately.
        """
        q = (query or "").strip()
        if not q:
            return []
        safe_limit = max(0, int(limit))
        terms = expand_search_terms([q])

        use_like = len(q) < 3
        params: list[Any] = []
        if use_like:
            sql = (
                "SELECT path, name, parent, size, mtime, ext "
                "FROM files WHERE ("
            )
            like_clauses: list[str] = []
            for term in terms:
                like = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                like_pattern = f"%{like}%"
                like_clauses.append(
                    "("
                    "name LIKE ? ESCAPE '\\' "
                    "OR parent LIKE ? ESCAPE '\\' "
                    "OR path LIKE ? ESCAPE '\\'"
                    ")"
                )
                params.extend([like_pattern, like_pattern, like_pattern])
            sql += " OR ".join(like_clauses) + ")"
            if exts:
                placeholders = ",".join("?" for _ in exts)
                sql += f" AND ext IN ({placeholders})"
                params.extend(e.lower() for e in exts)
            sql += " ORDER BY mtime DESC LIMIT ?"
            params.append(safe_limit)
        else:
            # `"q"` is the phrase-quoted form; without quoting the
            # tokenizer would treat hyphens / dots as punctuation
            # boundaries, dropping matches like `2025-report` when the
            # user types `report`.
            fts_q = " OR ".join('"' + term.replace('"', '""') + '"' for term in terms)
            params.append(fts_q)
            sql = (
                "SELECT f.path, f.name, f.parent, f.size, f.mtime, f.ext "
                "FROM files_fts JOIN files f ON f.rowid = files_fts.rowid "
                "WHERE files_fts MATCH ?"
            )
            if exts:
                placeholders = ",".join("?" for _ in exts)
                sql += f" AND f.ext IN ({placeholders})"
                params.extend(e.lower() for e in exts)
            sql += " ORDER BY bm25(files_fts), f.mtime DESC LIMIT ?"
            params.append(safe_limit)

        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [
            FastRow(
                path=r["path"],
                name=r["name"],
                parent=r["parent"],
                size=r["size"],
                mtime=r["mtime"],
                ext=r["ext"],
            )
            for r in rows
        ]

    def count(self) -> int:
        with self._lock:
            cur = self._conn.execute("SELECT COUNT(*) AS n FROM files")
            return int(cur.fetchone()["n"])

    def stats_by_ext(self, top: int = 20) -> list[tuple[str, int]]:
        with self._lock:
            cur = self._conn.execute(
                "SELECT ext, COUNT(*) AS n FROM files "
                "GROUP BY ext ORDER BY n DESC LIMIT ?",
                (int(top),),
            )
            return [(r["ext"], int(r["n"])) for r in cur]

    def close(self) -> None:
        with self._lock:
            try:
                self._conn.close()
            except Exception:  # noqa: BLE001
                pass
