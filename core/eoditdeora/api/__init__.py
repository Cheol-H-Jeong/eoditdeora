"""JSON-RPC over stdio API.

The Tauri shell spawns the Python sidecar as a child process and speaks
JSON-RPC 2.0 over its stdin/stdout. We keep stderr reserved for log output.

Framing: Content-Length header framing, same as LSP / Debug Adapter Protocol.
This is intentionally chosen over newline-delimited JSON because parsed
documents often contain embedded newlines in block text.
"""

from eoditdeora.api.rpc_server import RpcServer, run_stdio

__all__ = ["RpcServer", "run_stdio"]
