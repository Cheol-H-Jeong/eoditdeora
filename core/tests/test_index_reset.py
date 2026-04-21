from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from eoditdeora.api.rpc_server import ERR_INVALID_PARAMS, RpcServer
from eoditdeora.config.paths import get_paths


async def _call(server: RpcServer, method: str, params: dict[str, Any] | None = None):
    msg = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}
    return await server.handle_single(msg)


def _write_bytes(path: Path, size: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)


class _FakeDaemon:
    def __init__(self) -> None:
        self.stopped = 0
        self.started = 0

    def stop(self) -> None:
        self.stopped += 1

    def start(self) -> None:
        self.started += 1


@pytest.mark.asyncio
async def test_index_reset_deletes_index_artifacts_and_restarts_daemon(monkeypatch: pytest.MonkeyPatch):
    index_dir = get_paths().index
    _write_bytes(index_dir / "meta.sqlite3", 11)
    _write_bytes(index_dir / "history.sqlite3-shm", 13)
    _write_bytes(index_dir / "schema.sqlite3", 17)
    _write_bytes(index_dir / "fast_index.db", 19)
    _write_bytes(index_dir / "tantivy" / "seg.bin", 23)
    _write_bytes(index_dir / "lancedb" / "chunks.lance", 29)
    _write_bytes(index_dir / "settings.toml", 31)

    daemon = _FakeDaemon()
    monkeypatch.setattr("eoditdeora.indexer.daemon.get_daemon", lambda: daemon)

    server = RpcServer()
    resp = await _call(server, "index.reset", {"confirm": True})

    assert resp["result"] == {"ok": True, "deleted_bytes": 112, "restarted": True}
    assert daemon.stopped == 1
    assert daemon.started == 1
    assert not (index_dir / "meta.sqlite3").exists()
    assert not (index_dir / "history.sqlite3-shm").exists()
    assert not (index_dir / "schema.sqlite3").exists()
    assert not (index_dir / "fast_index.db").exists()
    assert not (index_dir / "tantivy").exists()
    assert not (index_dir / "lancedb").exists()
    assert (index_dir / "settings.toml").exists()


@pytest.mark.asyncio
async def test_index_reset_requires_confirm():
    server = RpcServer()
    resp = await _call(server, "index.reset", {})

    assert resp["error"]["code"] == ERR_INVALID_PARAMS

