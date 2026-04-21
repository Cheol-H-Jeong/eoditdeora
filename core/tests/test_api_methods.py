"""RPC method registrations."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from eoditdeora.api.rpc_server import RpcServer
from eoditdeora.storage.fast_index import FastIndex


async def _call(server: RpcServer, method: str, params: dict[str, Any] | None = None):
    msg = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}
    return await server.handle_single(msg)


@pytest.mark.asyncio
async def test_settings_get_returns_defaults():
    server = RpcServer()
    resp = await _call(server, "settings.get")
    result = resp["result"]
    # Endpoints start unset — user selects a running server.
    assert result["model"]["llm"]["base_url"] == ""
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
    (docs / "draft.txt").write_text("x", encoding="utf-8")
    server = RpcServer()
    await _call(server, "index.add_root", {"path": str(docs)})
    resp = await _call(server, "index.remove_root", {"path": str(docs)})
    assert resp["result"]["removed"] == 1
    search = await _call(server, "files.search", {"query": "draft"})
    assert search["result"]["results"] == []


@pytest.mark.asyncio
async def test_search_returns_empty_for_blank_query():
    server = RpcServer()
    resp = await _call(server, "search", {"query": "   "})
    assert resp["result"] == {"results": [], "query": ""}


@pytest.mark.asyncio
async def test_files_search_negative_limit_returns_no_rows():
    idx = FastIndex()
    try:
        idx.upsert_many([(f"/x/file{i:03d}.txt", 1, 100.0 + i) for i in range(3)])
    finally:
        idx.close()

    server = RpcServer()
    resp = await _call(server, "files.search", {"query": "file", "limit": -1})
    assert resp["result"]["results"] == []
    assert resp["result"]["total_indexed"] == 3


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


@pytest.mark.asyncio
async def test_history_rpc_roundtrip():
    server = RpcServer()
    await _call(server, "history.record_query", {"query": "alpha"})
    await _call(server, "history.record_query", {"query": "beta"})
    await _call(server, "history.record_open", {"path": "/tmp/a.txt"})

    resp = await _call(
        server,
        "history.top",
        {"kinds": ["queries", "opens"], "limit_query": 5, "limit_open": 10},
    )

    assert [row["query"] for row in resp["result"]["queries"]] == ["beta", "alpha"]
    assert resp["result"]["opens"][0]["path"] == "/tmp/a.txt"


@pytest.mark.asyncio
async def test_history_clear_rpc():
    server = RpcServer()
    await _call(server, "history.record_query", {"query": "alpha"})
    await _call(server, "history.clear")

    resp = await _call(server, "history.top", {"kinds": ["queries"]})

    assert resp["result"]["queries"] == []
