"""JSON-RPC 2.0 server with LSP-style Content-Length framing.

Runs either:
  * `run_stdio()` — reads from stdin, writes to stdout. This is how the
    Tauri shell talks to the sidecar in production.
  * `RpcServer.handle_single(message)` — pure function mode used in tests.

Keep the dispatcher tiny. All business logic lives in feature modules; this
file only routes and frames.
"""

from __future__ import annotations

import asyncio
import json
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from eoditdeora import __version__
from eoditdeora.api.methods import register_all
from eoditdeora.utils.logging import configure_logging, get_logger

log = get_logger(__name__)

RpcHandler = Callable[[dict[str, Any]], Awaitable[Any]]


@dataclass
class RpcError(Exception):
    code: int
    message: str
    data: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.data is not None:
            d["data"] = self.data
        return d


ERR_PARSE = -32700
ERR_INVALID_REQUEST = -32600
ERR_METHOD_NOT_FOUND = -32601
ERR_INVALID_PARAMS = -32602
ERR_INTERNAL = -32603

# Application-defined (JSON-RPC reserves -32000..-32099 for server errors).
# Used by upstream-facing clients so the UI can distinguish "your API key
# is missing" from "generic exception".
ERR_UPSTREAM_AUTH = -32010          # 401 / 403 from the model server
ERR_UPSTREAM_NOT_FOUND = -32011     # 404 — wrong base URL or model id
ERR_UPSTREAM_UNAVAILABLE = -32012   # 5xx or connection error
ERR_UPSTREAM_BAD_RESPONSE = -32013  # 200 but body not parseable
ERR_UPSTREAM_RATE_LIMIT = -32014    # 429 — upstream is throttling requests
ERR_OPEN_FAILED = -32015            # file open / launcher spawn failures
ERR_UPSTREAM_BAD_REQUEST = -32016   # 4xx — request rejected by upstream


class RpcServer:
    def __init__(self) -> None:
        self._handlers: dict[str, RpcHandler] = {}
        register_all(self)

    def register(self, name: str, handler: RpcHandler) -> None:
        if name in self._handlers:
            raise ValueError(f"duplicate handler registration: {name}")
        self._handlers[name] = handler

    async def handle_single(self, message: dict[str, Any]) -> dict[str, Any] | None:
        jsonrpc = message.get("jsonrpc")
        if jsonrpc != "2.0":
            return self._err_response(
                message.get("id"), ERR_INVALID_REQUEST, "jsonrpc must be '2.0'"
            )
        method = message.get("method")
        request_id = message.get("id")
        params = message.get("params") or {}

        if not isinstance(method, str):
            return self._err_response(request_id, ERR_INVALID_REQUEST, "missing method")
        if not isinstance(params, dict):
            return self._err_response(request_id, ERR_INVALID_PARAMS, "params must be object")

        handler = self._handlers.get(method)
        if handler is None:
            return self._err_response(request_id, ERR_METHOD_NOT_FOUND, f"unknown method: {method}")

        try:
            result = await handler(params)
        except RpcError as e:
            return self._err_response(request_id, e.code, e.message, e.data)
        except Exception as e:  # noqa: BLE001
            log.exception("rpc_handler_failed", method=method, error=str(e))
            return self._err_response(request_id, ERR_INTERNAL, f"{type(e).__name__}: {e}")

        # Notifications (no id) return None
        if request_id is None:
            return None
        return {"jsonrpc": "2.0", "id": request_id, "result": result}

    @staticmethod
    def _err_response(
        request_id: Any,
        code: int,
        message: str,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        if request_id is None:
            return None
        err: dict[str, Any] = {"code": code, "message": message}
        if data is not None:
            err["data"] = data
        return {"jsonrpc": "2.0", "id": request_id, "error": err}


async def _read_message(reader: asyncio.StreamReader) -> dict[str, Any] | None:
    # Read headers
    headers: dict[str, str] = {}
    while True:
        line = await reader.readline()
        if not line:
            return None
        decoded = line.decode("utf-8").rstrip("\r\n")
        if decoded == "":
            break
        if ":" not in decoded:
            continue
        k, v = decoded.split(":", 1)
        headers[k.strip().lower()] = v.strip()
    length_str = headers.get("content-length")
    if not length_str:
        return None
    length = int(length_str)
    body = await reader.readexactly(length)
    return json.loads(body)


def _write_message(writer: asyncio.StreamWriter, payload: dict[str, Any]) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
    writer.write(header)
    writer.write(body)


async def run_stdio() -> None:
    configure_logging()
    server = RpcServer()
    # Start the live indexer alongside the RPC loop so filesystem events
    # are observed from the first moment the UI is reachable.
    try:
        from eoditdeora.indexer.daemon import get_daemon

        get_daemon().start()
    except Exception as e:  # noqa: BLE001
        log.warning("daemon_start_failed", error=str(e))
    loop = asyncio.get_event_loop()

    reader = asyncio.StreamReader()
    protocol = asyncio.StreamReaderProtocol(reader)
    await loop.connect_read_pipe(lambda: protocol, sys.stdin)

    write_transport, _ = await loop.connect_write_pipe(
        asyncio.streams.FlowControlMixin, sys.stdout
    )
    writer = asyncio.StreamWriter(write_transport, protocol, reader, loop)

    log.info("rpc_server_started", version=__version__)
    try:
        while True:
            msg = await _read_message(reader)
            if msg is None:
                break
            response = await server.handle_single(msg)
            if response is not None:
                _write_message(writer, response)
                await writer.drain()
    finally:
        log.info("rpc_server_stopped")


def main() -> None:
    try:
        asyncio.run(run_stdio())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
