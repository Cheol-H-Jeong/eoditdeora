"""RPC glue for the collector: root management and status."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from eoditdeora.config import load_settings, save_settings
from eoditdeora.storage.fast_index import FastIndex
from eoditdeora.utils.logging import get_logger
from eoditdeora.utils.paths_util import normalize_path

log = get_logger(__name__)


def _is_same_or_descendant(path: Path, candidate_root: Path) -> bool:
    return path == candidate_root or candidate_root in path.parents


def _find_overlapping_root(path: Path, roots: list[Path]) -> Path | None:
    for root in roots:
        resolved = root.resolve()
        if _is_same_or_descendant(path, resolved) or _is_same_or_descendant(resolved, path):
            return resolved
    return None


async def add_root(path: str) -> dict[str, Any]:
    abs_path = normalize_path(path)
    if not abs_path.exists() or not abs_path.is_dir():
        return {"ok": False, "error": "not_a_directory", "path": str(abs_path)}

    settings = load_settings()
    roots = [Path(r) for r in settings.index.roots]
    resolved_roots = [r.resolve() for r in roots]
    if abs_path in resolved_roots:
        return {"ok": True, "already_registered": True, "path": str(abs_path)}
    overlap = _find_overlapping_root(abs_path, roots)
    if overlap is not None:
        return {
            "ok": False,
            "error": "overlaps_existing_root",
            "path": str(abs_path),
            "existing_root": str(overlap),
        }
    settings.index.roots.append(str(abs_path))
    save_settings(settings)
    log.info("root_added", path=str(abs_path))
    # Kick the indexer daemon so it starts watching this root right away.
    _refresh_indexer_daemon()
    return {"ok": True, "path": str(abs_path)}


async def remove_root(path: str) -> dict[str, Any]:
    abs_path = normalize_path(path)
    settings = load_settings()
    before = len(settings.index.roots)
    settings.index.roots = [
        r for r in settings.index.roots if Path(r).resolve() != abs_path
    ]
    removed = before - len(settings.index.roots)
    save_settings(settings)
    if removed:
        _refresh_indexer_daemon()
    removed_fast_rows = 0
    removed_content_docs = 0
    if removed:
        fast = FastIndex()
        try:
            removed_fast_rows = fast.delete_under(abs_path)
        finally:
            fast.close()
        removed_content_docs = _purge_root_content(abs_path)
    log.info("root_removed", path=str(abs_path), removed=removed)
    return {
        "ok": True,
        "removed": removed,
        "fast_index_removed": removed_fast_rows,
        "content_docs_removed": removed_content_docs,
    }


def _refresh_indexer_daemon() -> None:
    # Imported lazily so test helpers that don't want the daemon can
    # still use the service functions.
    from eoditdeora.indexer.daemon import get_daemon

    try:
        get_daemon().refresh_roots()
    except Exception as e:  # noqa: BLE001
        log.warning("daemon_refresh_failed", error=str(e))


def _purge_root_content(abs_path: Path) -> int:
    """Drop parsed/indexed content for a root that is no longer watched."""
    from eoditdeora.storage.fts import FtsStore
    from eoditdeora.storage.meta import MetaStore
    from eoditdeora.storage.vectors import VectorStore

    meta = MetaStore()
    try:
        rows = meta.list_documents_under_root(str(abs_path))
        if not rows:
            return 0
        fts = FtsStore()
        vectors = VectorStore()
        removed = 0
        for row in rows:
            doc_id = str(row["doc_id"])
            meta.delete_document(doc_id)
            fts.delete_doc(doc_id)
            vectors.delete_doc(doc_id)
            removed += 1
        return removed
    finally:
        meta.close()


async def status() -> dict[str, Any]:
    from eoditdeora.indexer.service import index_summary

    settings = load_settings()
    summary = await index_summary()
    return {
        "roots": settings.index.roots,
        "index": summary,
    }
