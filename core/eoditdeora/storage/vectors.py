"""LanceDB vector store.

One table: `chunks` with columns `chunk_id`, `doc_id`, `vector`, `text`.
LanceDB is an on-disk columnar store that speaks pyarrow, so we stage
batches through Arrow tables and let it handle ANN index building.

Embeddings are produced by the LLM runtime's dedicated embedding server
(bge-m3). The dimensionality constant below must match that model.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pyarrow as pa  # type: ignore[import-not-found]

from eoditdeora.config.paths import get_paths
from eoditdeora.utils.logging import get_logger

log = get_logger(__name__)

EMBED_DIM = 1024  # bge-m3 output dimension


def _list_table_names(db) -> list[str]:  # type: ignore[no-untyped-def]
    """Return known table names across LanceDB API versions.

    LanceDB 0.15 returns a flat list of strings from `table_names()` but
    paginates in `list_tables()` yielding `[('tables', [...]), ...]`. We
    normalize both paths to a plain list of string names.
    """
    # Prefer the stable `table_names()` API.
    if hasattr(db, "table_names"):
        import warnings as _w

        with _w.catch_warnings():
            _w.simplefilter("ignore", DeprecationWarning)
            names = db.table_names()
        flat: list[str] = []
        for item in names:
            if isinstance(item, str):
                flat.append(item)
            elif isinstance(item, tuple) and len(item) == 2 and item[0] == "tables":
                flat.extend(str(x) for x in item[1] or [])
        if flat:
            return flat
    if hasattr(db, "list_tables"):
        names = list(db.list_tables())
        flat = []
        for item in names:
            if isinstance(item, str):
                flat.append(item)
            elif isinstance(item, tuple) and len(item) == 2 and item[0] == "tables":
                flat.extend(str(x) for x in item[1] or [])
        return flat
    return []


def _schema() -> pa.Schema:
    return pa.schema(
        [
            pa.field("chunk_id", pa.string()),
            pa.field("doc_id", pa.string()),
            pa.field("text", pa.string()),
            pa.field("vector", pa.list_(pa.float32(), EMBED_DIM)),
        ]
    )


class VectorStore:
    def __init__(self, db_dir: Path | None = None, table_name: str = "chunks") -> None:
        self._dir = db_dir or (get_paths().index / "lancedb")
        self._dir.mkdir(parents=True, exist_ok=True)
        self._table_name = table_name
        self._db = None  # lazily opened
        self._table = None

    def _open(self) -> None:
        if self._db is not None:
            return
        import lancedb  # type: ignore[import-not-found]

        self._db = lancedb.connect(str(self._dir))
        existing = _list_table_names(self._db)
        if self._table_name in existing:
            self._table = self._db.open_table(self._table_name)
        else:
            empty = pa.table(
                {
                    "chunk_id": pa.array([], type=pa.string()),
                    "doc_id": pa.array([], type=pa.string()),
                    "text": pa.array([], type=pa.string()),
                    "vector": pa.array([], type=pa.list_(pa.float32(), EMBED_DIM)),
                },
                schema=_schema(),
            )
            self._table = self._db.create_table(self._table_name, data=empty)

    def upsert(self, records: list[dict[str, Any]]) -> None:
        if not records:
            return
        self._open()
        assert self._table is not None
        # LanceDB upsert: delete-by-chunk-id then add.
        ids = [r["chunk_id"] for r in records]
        expr = " OR ".join(f"chunk_id = '{cid}'" for cid in ids)
        try:
            self._table.delete(expr)
        except Exception as e:  # noqa: BLE001
            log.debug("lancedb_delete_skipped", error=str(e))
        self._table.add(records)

    def delete_doc(self, doc_id: str) -> None:
        self._open()
        assert self._table is not None
        self._table.delete(f"doc_id = '{doc_id}'")

    def search(self, vector: list[float], top_k: int = 50) -> list[dict[str, Any]]:
        self._open()
        assert self._table is not None
        it = self._table.search(vector).limit(top_k).to_list()
        return [dict(r) for r in it]
