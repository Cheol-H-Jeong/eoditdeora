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


async def _files_search(params: dict[str, Any]) -> dict[str, Any]:
    """Everything-tier file-name search.

    Intentionally cheap: <50 ms for tens of thousands of indexed files.
    Returns raw paths + metadata so the UI can render instantly as the
    user types. For body-text or semantic search, callers use the
    `search` method with mode="search"/"ask".
    """
    from eoditdeora.storage.fast_index import FastIndex

    query = str(params.get("query", "")).strip()
    limit = int(params.get("limit", 50))
    exts_raw = params.get("exts")
    exts: list[str] | None = None
    if isinstance(exts_raw, list) and exts_raw:
        exts = [str(e).lower() for e in exts_raw]
    idx = FastIndex()
    try:
        rows = idx.search(query, limit=limit, exts=exts)
        return {
            "query": query,
            "results": [r.to_dict() for r in rows],
            "total_indexed": idx.count(),
        }
    finally:
        idx.close()


async def _files_stats(_: dict[str, Any]) -> dict[str, Any]:
    from eoditdeora.storage.fast_index import FastIndex

    idx = FastIndex()
    try:
        return {
            "total": idx.count(),
            "by_ext": [{"ext": e, "count": n} for e, n in idx.stats_by_ext()],
        }
    finally:
        idx.close()


async def _index_rescan(_: dict[str, Any]) -> dict[str, Any]:
    """Trigger a fast-index rescan of every registered root.

    Used after the user broadens the extension set or removes files
    outside the app. Walks each root and mirrors entries into the fast
    index; content indexing continues on its own schedule.
    """
    from eoditdeora.indexer.fast_scan import rescan_all

    return await rescan_all()


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


async def _open_file(params: dict[str, Any]) -> dict[str, Any]:
    """Launch a file with the OS default application.

    Linux  → xdg-open
    macOS  → open
    Windows→ start (via `os.startfile`)

    Only paths that exist on disk are opened; anything else returns
    a structured error so the UI can surface it.
    """
    import os
    import subprocess
    import sys
    from pathlib import Path

    from eoditdeora.api.rpc_server import ERR_INVALID_PARAMS, RpcError

    raw = params.get("path")
    if not raw:
        raise RpcError(ERR_INVALID_PARAMS, "missing 'path'")
    target = Path(str(raw)).expanduser()
    if not target.exists():
        return {"ok": False, "error": "not_found", "path": str(target)}

    try:
        if sys.platform == "win32":
            os.startfile(str(target))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(target)], close_fds=True)  # noqa: S603,S607
        else:
            subprocess.Popen(  # noqa: S603
                ["xdg-open", str(target)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
                start_new_session=True,
            )
    except FileNotFoundError as e:
        return {"ok": False, "error": "launcher_missing", "detail": str(e)}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": "spawn_failed", "detail": str(e)}
    return {"ok": True, "path": str(target)}


async def _indexer_status(_: dict[str, Any]) -> dict[str, Any]:
    from eoditdeora.indexer.daemon import get_daemon

    return {"running": True, "stats": get_daemon().stats()}


async def _autostart_enable(_: dict[str, Any]) -> dict[str, Any]:
    from eoditdeora.runtime.autostart import enable

    return dict(enable())


async def _autostart_disable(_: dict[str, Any]) -> dict[str, Any]:
    from eoditdeora.runtime.autostart import disable

    return dict(disable())


async def _autostart_status(_: dict[str, Any]) -> dict[str, Any]:
    from eoditdeora.runtime.autostart import status

    return dict(status())


async def _endpoints_health(_: dict[str, Any]) -> dict[str, Any]:
    from eoditdeora.runtime.supervisor import RuntimeSupervisor

    return {"roles": RuntimeSupervisor().health()}


async def _endpoints_discover(_: dict[str, Any]) -> dict[str, Any]:
    from eoditdeora.runtime.endpoints import discover_local

    return {"endpoints": [p.to_dict() for p in discover_local()]}


async def _endpoints_test(params: dict[str, Any]) -> dict[str, Any]:
    from eoditdeora.runtime.endpoints import probe

    base_url = str(params.get("base_url") or "")
    api_key = str(params.get("api_key") or "")
    api_kind = str(params.get("api_kind") or "openai")
    return probe(base_url, api_key=api_key, api_kind=api_kind).to_dict()


async def _endpoints_presets(_: dict[str, Any]) -> dict[str, Any]:
    from eoditdeora.runtime.presets import list_presets

    return {"presets": list_presets()}


async def _endpoints_auto_connect(params: dict[str, Any]) -> dict[str, Any]:
    """Re-run the auto-connection scan on demand.

    Params:
      force (bool) — when true, reassign every role even if the user
                     had already set one. Default false (only fills
                     empty roles).
    """
    from eoditdeora.runtime.auto_connect import auto_connect

    return auto_connect(force=bool(params.get("force")))


async def _endpoints_update(params: dict[str, Any]) -> dict[str, Any]:
    """Write one role's endpoint config.

    params: {"role": "llm|embed|rerank", "endpoint": {base_url, model_id, api_key, api_kind}}
    """
    from eoditdeora.api.rpc_server import ERR_INVALID_PARAMS, RpcError
    from eoditdeora.config import load_settings, save_settings
    from eoditdeora.config.settings import EndpointConfig

    role = str(params.get("role") or "")
    if role not in {"llm", "embed", "rerank"}:
        raise RpcError(ERR_INVALID_PARAMS, f"unknown role: {role!r}")
    raw = params.get("endpoint") or {}
    if not isinstance(raw, dict):
        raise RpcError(ERR_INVALID_PARAMS, "endpoint must be an object")
    try:
        endpoint = EndpointConfig.model_validate(raw)
    except Exception as e:  # noqa: BLE001
        raise RpcError(ERR_INVALID_PARAMS, f"invalid endpoint: {e}") from e

    settings = load_settings()
    setattr(settings.model, role, endpoint)
    save_settings(settings)
    return {"ok": True, "role": role, "endpoint": endpoint.model_dump(mode="json")}


async def _docpaths_discover(_: dict[str, Any]) -> dict[str, Any]:
    """Enumerate well-known document folders on this OS.

    Returns every candidate (even non-existent ones) so the UI can show
    a "not installed" badge for missing OneDrive etc. The UI filters
    to `has_documents=True` for the default "add all" action but keeps
    the rest as opt-in toggles.
    """
    from eoditdeora.runtime.docpath_discovery import discover

    return {"candidates": [r.to_dict() for r in discover()]}


async def _docpaths_add_defaults(_: dict[str, Any]) -> dict[str, Any]:
    """Add every discovered root that contains documents.

    Idempotent: already-registered roots are silently skipped by
    `collector.add_root`.
    """
    from eoditdeora.collector.service import add_root
    from eoditdeora.runtime.docpath_discovery import default_roots

    added: list[str] = []
    skipped: list[str] = []
    for candidate in default_roots():
        result = await add_root(candidate)
        if result.get("ok"):
            added.append(candidate)
        else:
            skipped.append(candidate)
    return {"added": added, "skipped": skipped}


async def _first_run_bootstrap(params: dict[str, Any]) -> dict[str, Any]:
    """Idempotent first-launch bootstrap.

    Safe to call on every launch: if a default root already exists we
    don't re-add it, if autostart is already on we skip, if an endpoint
    role is already configured we leave it alone.

    params.force_reconnect=true → reassign every role even if set.
    """
    from pathlib import Path

    from eoditdeora.collector.service import add_root
    from eoditdeora.config import load_settings
    from eoditdeora.runtime.auto_connect import auto_connect
    from eoditdeora.runtime.autostart import enable as enable_autostart
    from eoditdeora.runtime.autostart import status as autostart_status

    actions: list[str] = []
    settings = load_settings()

    if not settings.index.roots:
        # Expanded first-run discovery: add every well-known doc folder
        # on this platform that actually contains parseable documents.
        # Previously we stopped at the first match (usually ~/Documents),
        # missing Desktop / Downloads / OneDrive / 문서 where Korean
        # office users keep most of their work.
        from eoditdeora.runtime.docpath_discovery import default_roots

        for candidate in default_roots():
            result = await add_root(candidate)
            if result.get("ok"):
                actions.append(f"added_root:{candidate}")

    if not autostart_status().get("enabled"):
        enable_autostart()
        actions.append("autostart_enabled")

    # Scan localhost and auto-assign any unconfigured LLM/embed/rerank
    # role to an already-running server. Never overwrites explicit
    # settings unless force_reconnect is set.
    force = bool(params.get("force_reconnect"))
    ac = auto_connect(force=force)
    actions.extend([str(a) for a in ac.get("actions", [])])

    return {
        "actions": actions,
        "roots": load_settings().index.roots,
        "auto_connect": ac,
    }


def register_all(server: RpcServer) -> None:
    server.register("ping", _ping)
    server.register("settings.get", _get_settings)
    server.register("settings.update", _update_settings)
    server.register("search", _search)
    server.register("files.search", _files_search)
    server.register("files.stats", _files_stats)
    server.register("index.rescan", _index_rescan)
    server.register("index.add_root", _index_add_root)
    server.register("index.remove_root", _index_remove_root)
    server.register("index.status", _index_status)
    server.register("indexer.status", _indexer_status)
    server.register("autostart.enable", _autostart_enable)
    server.register("autostart.disable", _autostart_disable)
    server.register("autostart.status", _autostart_status)
    server.register("docpaths.discover", _docpaths_discover)
    server.register("docpaths.add_defaults", _docpaths_add_defaults)
    server.register("endpoints.health", _endpoints_health)
    server.register("endpoints.discover", _endpoints_discover)
    server.register("endpoints.test", _endpoints_test)
    server.register("endpoints.update", _endpoints_update)
    server.register("endpoints.auto_connect", _endpoints_auto_connect)
    server.register("endpoints.presets", _endpoints_presets)
    server.register("first_run.bootstrap", _first_run_bootstrap)
    server.register("forget", _forget)
    server.register("open_file", _open_file)
