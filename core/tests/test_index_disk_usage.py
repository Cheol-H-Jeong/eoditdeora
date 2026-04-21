from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from eoditdeora.api.rpc_server import RpcServer
from eoditdeora.config.paths import get_paths


async def _call(server: RpcServer, method: str, params: dict[str, Any] | None = None):
    msg = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}
    return await server.handle_single(msg)


def _write_bytes(path: Path, size: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)


@pytest.mark.asyncio
async def test_index_disk_usage_sums_by_store():
    index_dir = get_paths().index
    _write_bytes(index_dir / "meta.sqlite3", 11)
    _write_bytes(index_dir / "history.sqlite3-wal", 13)
    _write_bytes(index_dir / "schema.sqlite3", 17)
    _write_bytes(index_dir / "fast_index.db", 19)
    _write_bytes(index_dir / "tantivy" / "seg.bin", 23)
    _write_bytes(index_dir / "lancedb" / "chunks.lance", 29)
    _write_bytes(index_dir / "misc.bin", 31)

    server = RpcServer()
    resp = await _call(server, "index.disk_usage")

    assert resp["result"]["index_dir"] == str(index_dir)
    assert resp["result"]["by_store"] == {
        "meta": 11,
        "fts": 23,
        "vectors": 29,
        "fast_index": 19,
        "history": 13,
        "schema": 17,
        "other": 31,
    }
    assert resp["result"]["total_bytes"] == 143


@pytest.mark.asyncio
async def test_index_disk_usage_uses_ttl_cache():
    index_dir = get_paths().index
    marker = index_dir / "meta.sqlite3"
    _write_bytes(marker, 10)

    server = RpcServer()
    first = await _call(server, "index.disk_usage")
    _write_bytes(marker, 20)
    second = await _call(server, "index.disk_usage")

    assert first["result"]["total_bytes"] == 10
    assert second["result"]["total_bytes"] == 10

