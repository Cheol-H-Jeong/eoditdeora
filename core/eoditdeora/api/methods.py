"""RPC method registrations.

This module is the single place the UI contract is listed. Keep handlers
thin; delegate heavy lifting to feature modules.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from eoditdeora import __version__
from eoditdeora.config import load_settings, save_settings
from eoditdeora.config.settings import Settings

if TYPE_CHECKING:
    from eoditdeora.api.rpc_server import RpcServer


async def _ping(_: dict[str, Any]) -> dict[str, Any]:
    return {"ok": True, "version": __version__}


async def _get_settings(_: dict[str, Any]) -> dict[str, Any]:
    return load_settings().model_dump(mode="json")


async def _update_settings(params: dict[str, Any]) -> dict[str, Any]:
    # UI sends full settings object; we validate then persist.
    settings = Settings.model_validate(params)
    save_settings(settings)
    return settings.model_dump(mode="json")


async def _search(params: dict[str, Any]) -> dict[str, Any]:
    from eoditdeora.retriever.service import search as do_search

    query = str(params.get("query", "")).strip()
    if not query:
        return {"results": [], "query": ""}
    top_k = int(params.get("top_k", 10))
    mode = str(params.get("mode", "search"))  # "search" | "ask"
    return await do_search(query=query, top_k=top_k, mode=mode)


async def _index_add_root(params: dict[str, Any]) -> dict[str, Any]:
    from eoditdeora.collector.service import add_root

    path = str(params["path"])
    return await add_root(path)


async def _index_remove_root(params: dict[str, Any]) -> dict[str, Any]:
    from eoditdeora.collector.service import remove_root

    path = str(params["path"])
    return await remove_root(path)


async def _index_status(_: dict[str, Any]) -> dict[str, Any]:
    from eoditdeora.collector.service import status

    return await status()


async def _forget(params: dict[str, Any]) -> dict[str, Any]:
    """D3/D4 compliance: remove an item completely from the index."""
    from eoditdeora.indexer.service import forget

    return await forget(
        doc_ids=params.get("doc_ids") or [],
        paths=params.get("paths") or [],
        entities=params.get("entities") or [],
    )


def register_all(server: RpcServer) -> None:
    server.register("ping", _ping)
    server.register("settings.get", _get_settings)
    server.register("settings.update", _update_settings)
    server.register("search", _search)
    server.register("index.add_root", _index_add_root)
    server.register("index.remove_root", _index_remove_root)
    server.register("index.status", _index_status)
    server.register("forget", _forget)
