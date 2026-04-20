"""RPC glue for the collector: root management and status."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from eoditdeora.config import load_settings, save_settings
from eoditdeora.utils.logging import get_logger
from eoditdeora.utils.paths_util import normalize_path

log = get_logger(__name__)


async def add_root(path: str) -> dict[str, Any]:
    abs_path = normalize_path(path)
    if not abs_path.exists() or not abs_path.is_dir():
        return {"ok": False, "error": "not_a_directory", "path": str(abs_path)}

    settings = load_settings()
    roots = [Path(r) for r in settings.index.roots]
    if abs_path in [r.resolve() for r in roots]:
        return {"ok": True, "already_registered": True, "path": str(abs_path)}
    settings.index.roots.append(str(abs_path))
    save_settings(settings)
    log.info("root_added", path=str(abs_path))
    # Indexer pickup happens via the orchestrator; in the sidecar skeleton
    # we surface the registration immediately and let the background loop
    # start scanning on next tick.
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
    log.info("root_removed", path=str(abs_path), removed=removed)
    return {"ok": True, "removed": removed}


async def status() -> dict[str, Any]:
    from eoditdeora.indexer.service import index_summary

    settings = load_settings()
    summary = await index_summary()
    return {
        "roots": settings.index.roots,
        "index": summary,
    }
