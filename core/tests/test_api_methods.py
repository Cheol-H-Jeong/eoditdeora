"""RPC method registrations."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from eoditdeora.api.rpc_server import RpcServer


async def _call(server: RpcServer, method: str, params: dict[str, Any] | None = None):
    msg = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}
    return await server.handle_single(msg)


@pytest.mark.asyncio
async def test_settings_get_returns_defaults():
    server = RpcServer()
    resp = await _call(server, "settings.get")
    result = resp["result"]
    assert result["model"]["llm_model_id"] == "gemma-4-26b-a4b-it"
    assert result["search"]["strict_provenance"] is True


@pytest.mark.asyncio
async def test_settings_update_persists():
    server = RpcServer()
    current = (await _call(server, "settings.get"))["result"]
    current["index"]["max_file_bytes"] = 10000
    resp = await _call(server, "settings.update", current)
    assert resp["result"]["index"]["max_file_bytes"] == 10000
    # reload and confirm
    refetched = (await _call(server, "settings.get"))["result"]
    assert refetched["index"]["max_file_bytes"] == 10000


@pytest.mark.asyncio
async def test_index_add_root_and_status(tmp_path: Path):
    # Use a subdirectory so the live-watcher daemon has nothing to index.
    docs = tmp_path / "watched"
    docs.mkdir()
    server = RpcServer()
    resp = await _call(server, "index.add_root", {"path": str(docs)})
    assert resp["result"]["ok"] is True
    status = (await _call(server, "index.status"))["result"]
    assert str(docs.resolve()) in status["roots"]
    assert status["index"]["doc_count"] == 0


@pytest.mark.asyncio
async def test_index_remove_root(tmp_path: Path):
    docs = tmp_path / "watched"
    docs.mkdir()
    server = RpcServer()
    await _call(server, "index.add_root", {"path": str(docs)})
    resp = await _call(server, "index.remove_root", {"path": str(docs)})
    assert resp["result"]["removed"] == 1


@pytest.mark.asyncio
async def test_search_returns_empty_for_blank_query():
    server = RpcServer()
    resp = await _call(server, "search", {"query": "   "})
    assert resp["result"] == {"results": [], "query": ""}


@pytest.mark.asyncio
async def test_forget_removes_records():
    server = RpcServer()
    resp = await _call(
        server, "forget", {"doc_ids": [], "paths": [], "entities": []}
    )
    assert resp["result"]["ok"] is True


@pytest.mark.asyncio
async def test_invalid_params_returns_error_code():
    server = RpcServer()
    msg = {"jsonrpc": "2.0", "id": 42, "method": "search", "params": "not an object"}
    resp = await server.handle_single(msg)
    assert resp["error"]["code"] == -32602
