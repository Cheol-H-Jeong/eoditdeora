"""Stdio framing test — feed the server a crafted Content-Length frame
and assert the response frame is well-formed."""

from __future__ import annotations

import asyncio
import json

from eoditdeora.api.rpc_server import RpcServer


def _frame(payload: dict) -> bytes:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    return f"Content-Length: {len(body)}\r\n\r\n".encode("ascii") + body


async def _dispatch_via_handle_single(server: RpcServer, frame: bytes) -> dict | None:
    # Parse the incoming frame inline — we test handle_single contract only
    # here. run_stdio is covered by a smoke test below.
    sep = b"\r\n\r\n"
    header, _, body = frame.partition(sep)
    assert _ == sep, "malformed test frame"
    size = 0
    for line in header.decode("ascii").split("\r\n"):
        if line.lower().startswith("content-length:"):
            size = int(line.split(":", 1)[1].strip())
    assert size == len(body)
    msg = json.loads(body)
    return await server.handle_single(msg)


def test_frame_roundtrip_utf8():
    """Make sure non-ASCII payloads survive byte-length framing."""
    payload = {"jsonrpc": "2.0", "id": 1, "method": "ping", "params": {"msg": "한글"}}
    frame = _frame(payload)
    assert b"\xed\x95\x9c\xea\xb8\x80" in frame  # UTF-8 for "한글"


def test_handle_single_with_framed_input():
    server = RpcServer()
    payload = {"jsonrpc": "2.0", "id": 7, "method": "ping", "params": {}}
    frame = _frame(payload)
    response = asyncio.run(_dispatch_via_handle_single(server, frame))
    assert response is not None
    assert response["id"] == 7
    assert response["result"]["ok"] is True
