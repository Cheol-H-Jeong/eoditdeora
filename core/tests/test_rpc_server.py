import pytest

from eoditdeora.api.rpc_server import RpcServer


@pytest.mark.asyncio
async def test_ping_returns_version():
    server = RpcServer()
    msg = {"jsonrpc": "2.0", "id": 1, "method": "ping", "params": {}}
    resp = await server.handle_single(msg)
    assert resp is not None
    assert resp["id"] == 1
    assert resp["result"]["ok"] is True
    assert "version" in resp["result"]


@pytest.mark.asyncio
async def test_unknown_method_returns_error():
    server = RpcServer()
    msg = {"jsonrpc": "2.0", "id": 2, "method": "no_such", "params": {}}
    resp = await server.handle_single(msg)
    assert resp is not None
    assert resp["error"]["code"] == -32601


@pytest.mark.asyncio
async def test_notification_returns_none():
    server = RpcServer()
    msg = {"jsonrpc": "2.0", "method": "ping", "params": {}}  # no id = notification
    resp = await server.handle_single(msg)
    assert resp is None


@pytest.mark.asyncio
async def test_invalid_jsonrpc_version():
    server = RpcServer()
    msg = {"jsonrpc": "1.0", "id": 3, "method": "ping", "params": {}}
    resp = await server.handle_single(msg)
    assert resp is not None
    assert resp["error"]["code"] == -32600
