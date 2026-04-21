"""SQLite metadata store.

Schema:

documents      one row per indexed file. Holds path, hashes, parse metadata,
               summaries, and last-seen timestamps.
chunks         sub-document windows we embed and retrieve. Each chunk
               points to its document and stores offsets for snippet highlight.
entities       extracted proper nouns (people, organizations, sums, dates).
               One row per (doc, entity, kind) triple.
relations      subject-predicate-object triples extracted during the
               Understand stage. Used by the graph view.
jobs           durable queue of pending work (parse, embed, understand).
               Idempotent; a crashed worker restarts with no data loss.

We keep SQLite as the single place all identifiers live. Other stores
(LanceDB, Tantivy) only hold derivatives and can be rebuilt from here.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from eoditdeora.config.paths import get_paths
from eoditdeora.storage.schema_version import CURRENT_SCHEMA_VERSION, ensure_version
from eoditdeora.utils.logging import get_logger
from eoditdeora.utils.paths_util import display_path

log = get_logger(__name__)

_SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;
PRAGMA synchronous = NORMAL;

CREATE TABLE IF NOT EXISTS documents (
    doc_id             TEXT PRIMARY KEY,            -- sha256:... content hash
    root               TEXT NOT NULL,
    source_path        TEXT NOT NULL UNIQUE,
    source_path_display TEXT NOT NULL,
    format             TEXT NOT NULL,
    parser             TEXT,
    fidelity           INTEGER,
    size_bytes         INTEGER NOT NULL,
    mtime_ns           INTEGER NOT NULL,
    indexed_at         INTEGER NOT NULL,            -- unix ns
    classification     TEXT,                        -- 품의서/회의록/…
    summary_oneline    TEXT,
    summary_paragraph  TEXT,
    summary_detailed   TEXT,
    language           TEXT,
    warnings_json      TEXT,
    metadata_json      TEXT
);

CREATE INDEX IF NOT EXISTS idx_documents_root ON documents(root);
CREATE INDEX IF NOT EXISTS idx_documents_format ON documents(format);
CREATE INDEX IF NOT EXISTS idx_documents_classification ON documents(classification);
CREATE INDEX IF NOT EXISTS idx_documents_indexed_at ON documents(indexed_at);

CREATE TABLE IF NOT EXISTS chunks (
    chunk_id           TEXT PRIMARY KEY,            -- doc_id:chunk_ordinal
    doc_id             TEXT NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
    ordinal            INTEGER NOT NULL,
    block_type         TEXT,
    page               INTEGER,
    sheet              TEXT,
    text               TEXT NOT NULL,
    char_start         INTEGER,
    char_end           INTEGER,
    token_count        INTEGER,
    UNIQUE(doc_id, ordinal)
);

CREATE INDEX IF NOT EXISTS idx_chunks_doc ON chunks(doc_id);

CREATE TABLE IF NOT EXISTS entities (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id             TEXT NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
    kind               TEXT NOT NULL,               -- person/org/project/money/date/phone/account/place
    value              TEXT NOT NULL,
    normalized         TEXT,
    confidence         REAL,
    UNIQUE(doc_id, kind, value)
);

CREATE INDEX IF NOT EXISTS idx_entities_kind_value ON entities(kind, value);

CREATE TABLE IF NOT EXISTS relations (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id             TEXT NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
    subject            TEXT NOT NULL,
    predicate          TEXT NOT NULL,
    object             TEXT NOT NULL,
    observed_at        INTEGER,
    context_chunk_id   TEXT REFERENCES chunks(chunk_id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_relations_subject ON relations(subject);
CREATE INDEX IF NOT EXISTS idx_relations_object ON relations(object);

CREATE TABLE IF NOT EXISTS jobs (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    kind               TEXT NOT NULL,               -- parse/embed/understand/ocr
    payload_json       TEXT NOT NULL,
    priority           INTEGER NOT NULL DEFAULT 100,
    attempts           INTEGER NOT NULL DEFAULT 0,
    last_error         TEXT,
    created_at         INTEGER NOT NULL,
    claimed_at         INTEGER,
    completed_at       INTEGER
);

CREATE INDEX IF NOT EXISTS idx_jobs_kind_priority ON jobs(kind, priority, id);
CREATE INDEX IF NOT EXISTS idx_jobs_pending ON jobs(completed_at) WHERE completed_at IS NULL;
"""


class MetaStore:
    """Thin wrapper over sqlite3 with typed helpers.

    The connection is per-instance; callers using threads should create
    one `MetaStore` per thread. Writes are serialized inside SQLite's WAL.
    """

    def __init__(self, db_path: Path | None = None) -> None:
        self._path = db_path or (get_paths().index / "meta.sqlite3")
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        ensure_version(
            self._path.parent,
            "meta",
            CURRENT_SCHEMA_VERSION,
            self._rebuild_schema,
        )
        self._init_schema()

    def _init_schema(self) -> None:
        with self._conn:
            self._conn.executescript(_SCHEMA)

    def _rebuild_schema(self) -> None:
        with self._conn:
            self._conn.executescript(
                """
                DROP TABLE IF EXISTS relations;
                DROP TABLE IF EXISTS entities;
                DROP TABLE IF EXISTS chunks;
                DROP TABLE IF EXISTS jobs;
                DROP TABLE IF EXISTS documents;
                """
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

    # --- Documents -------------------------------------------------------

    def upsert_document(self, record: dict[str, Any]) -> None:
        with self.tx() as cur:
            cur.execute(
                """
                INSERT INTO documents
                    (doc_id, root, source_path, source_path_display, format, parser,
                     fidelity, size_bytes, mtime_ns, indexed_at, classification,
                     summary_oneline, summary_paragraph, summary_detailed,
                     language, warnings_json, metadata_json)
                VALUES
                    (:doc_id, :root, :source_path, :source_path_display, :format, :parser,
                     :fidelity, :size_bytes, :mtime_ns, :indexed_at, :classification,
                     :summary_oneline, :summary_paragraph, :summary_detailed,
                     :language, :warnings_json, :metadata_json)
                ON CONFLICT(doc_id) DO UPDATE SET
                    root=excluded.root,
                    source_path=excluded.source_path,
                    source_path_display=excluded.source_path_display,
                    format=excluded.format,
                    parser=excluded.parser,
                    fidelity=excluded.fidelity,
                    size_bytes=excluded.size_bytes,
                    mtime_ns=excluded.mtime_ns,
                    indexed_at=excluded.indexed_at,
                    warnings_json=excluded.warnings_json,
                    metadata_json=excluded.metadata_json
                """,
                record,
            )

    def delete_document(self, doc_id: str) -> None:
        with self.tx() as cur:
            cur.execute("DELETE FROM documents WHERE doc_id = ?", (doc_id,))

    def replace_path(
        self,
        old_path: str,
        new_path: str,
        *,
        new_root: str | None = None,
    ) -> tuple[str, str | None] | None:
        """Move one document row to a new source path without changing doc_id.

        Returns the moved doc_id and, when the destination path already
        belonged to another document, the displaced doc_id so callers can
        purge derivative stores keyed outside SQLite.
        """
        new_display = display_path(Path(new_path))
        with self.tx() as cur:
            cur.execute(
                "SELECT doc_id FROM documents WHERE source_path = ?",
                (old_path,),
            )
            row = cur.fetchone()
            if not row:
                return None
            doc_id = str(row["doc_id"])
            cur.execute(
                "SELECT doc_id FROM documents WHERE source_path = ?",
                (new_path,),
            )
            existing = cur.fetchone()
            displaced_doc_id: str | None = None
            if existing and str(existing["doc_id"]) != doc_id:
                displaced_doc_id = str(existing["doc_id"])
                cur.execute("DELETE FROM documents WHERE doc_id = ?", (displaced_doc_id,))
            cur.execute(
                """
                UPDATE documents
                   SET source_path = ?,
                       source_path_display = ?,
                       root = COALESCE(?, root)
                 WHERE doc_id = ?
                """,
                (new_path, new_display, new_root, doc_id),
            )
            return doc_id, displaced_doc_id

    def get_document_by_path(self, path: str) -> dict[str, Any] | None:
        cur = self._conn.execute(
            "SELECT * FROM documents WHERE source_path = ?", (path,)
        )
        row = cur.fetchone()
        return dict(row) if row else None

    def get_document(self, doc_id: str) -> dict[str, Any] | None:
        cur = self._conn.execute(
            "SELECT * FROM documents WHERE doc_id = ?", (doc_id,)
        )
        row = cur.fetchone()
        return dict(row) if row else None

    def list_documents_under_root(self, root: str) -> list[dict[str, Any]]:
        cur = self._conn.execute(
            "SELECT doc_id, source_path, format FROM documents WHERE root = ?",
            (root,),
        )
        return [dict(row) for row in cur.fetchall()]

    def count_documents(self) -> int:
        cur = self._conn.execute("SELECT COUNT(*) AS n FROM documents")
        return int(cur.fetchone()["n"])

    # --- Chunks ----------------------------------------------------------

    def replace_chunks(self, doc_id: str, chunks: list[dict[str, Any]]) -> None:
        with self.tx() as cur:
            cur.execute("DELETE FROM chunks WHERE doc_id = ?", (doc_id,))
            cur.executemany(
                """
                INSERT INTO chunks
                    (chunk_id, doc_id, ordinal, block_type, page, sheet,
                     text, char_start, char_end, token_count)
                VALUES
                    (:chunk_id, :doc_id, :ordinal, :block_type, :page, :sheet,
                     :text, :char_start, :char_end, :token_count)
                """,
                chunks,
            )

    def get_chunks_for_doc(self, doc_id: str) -> list[dict[str, Any]]:
        cur = self._conn.execute(
            "SELECT * FROM chunks WHERE doc_id = ? ORDER BY ordinal", (doc_id,)
        )
        return [dict(r) for r in cur.fetchall()]

    # --- Jobs ------------------------------------------------------------

    def enqueue_job(self, kind: str, payload_json: str, priority: int = 100) -> int:
        import time

        with self.tx() as cur:
            cur.execute(
                """
                INSERT INTO jobs (kind, payload_json, priority, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (kind, payload_json, priority, time.time_ns()),
            )
            return int(cur.lastrowid or 0)

    def claim_job(self, kind: str) -> dict[str, Any] | None:
        import time

        with self.tx() as cur:
            cur.execute(
                """
                SELECT * FROM jobs
                WHERE kind = ? AND completed_at IS NULL AND claimed_at IS NULL
                ORDER BY priority, id
                LIMIT 1
                """,
                (kind,),
            )
            row = cur.fetchone()
            if not row:
                return None
            cur.execute(
                "UPDATE jobs SET claimed_at = ? WHERE id = ?",
                (time.time_ns(), row["id"]),
            )
            return dict(row)

    def complete_job(self, job_id: int, error: str | None = None) -> None:
        import time

        with self.tx() as cur:
            if error is None:
                cur.execute(
                    "UPDATE jobs SET completed_at = ?, last_error = NULL WHERE id = ?",
                    (time.time_ns(), job_id),
                )
            else:
                cur.execute(
                    """UPDATE jobs
                         SET claimed_at = NULL,
                             attempts = attempts + 1,
                             last_error = ?
                       WHERE id = ?""",
                    (error, job_id),
                )

    def close(self) -> None:
        self._conn.close()
