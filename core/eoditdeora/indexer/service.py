"""RPC-facing index operations (status, forget)."""

from __future__ import annotations

from typing import Any

from eoditdeora.storage.fts import FtsStore
from eoditdeora.storage.meta import MetaStore
from eoditdeora.storage.vectors import VectorStore
from eoditdeora.utils.logging import get_logger

log = get_logger(__name__)


async def index_summary() -> dict[str, Any]:
    meta = MetaStore()
    try:
        return {"doc_count": meta.count_documents(), "db_path": str(meta.path)}
    finally:
        meta.close()


async def forget(
    doc_ids: list[str],
    paths: list[str],
    entities: list[str],
) -> dict[str, Any]:
    """D3/D4 compliance: purge records. Originals on disk are never touched."""
    meta = MetaStore()
    fts = FtsStore()
    vec = VectorStore()
    removed = 0
    try:
        for doc_id in doc_ids:
            meta.delete_document(doc_id)
            fts.delete_doc(doc_id)
            vec.delete_doc(doc_id)
            removed += 1
        for path in paths:
            existing = meta.get_document_by_path(path)
            if not existing:
                continue
            did = existing["doc_id"]
            meta.delete_document(did)
            fts.delete_doc(did)
            vec.delete_doc(did)
            removed += 1
    finally:
        meta.close()
    log.info("forget_applied", removed=removed, entity_filters=len(entities))
    return {"ok": True, "removed": removed}
