#!/usr/bin/env python3
"""Development HTTP bridge — lets us preview the Svelte UI in a browser
without the Tauri native shell.

Serves:
  * GET  /         → built UI (apps/ui/build). The index.html is patched
                     to inject a Tauri-invoke shim that posts to /rpc.
  * POST /rpc      → JSON-RPC passthrough to the Python API layer.

This is ONLY for local development / screenshots. Production path is
Tauri + PyInstaller sidecar, which is unchanged.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "apps" / "ui" / "build"

sys.path.insert(0, str(ROOT / "core"))
os.environ.setdefault("EODITDEORA_HOME", str(ROOT / ".demo-home"))

from eoditdeora.api.rpc_server import RpcServer  # noqa: E402

SHIM = b"""
<script>
  // Minimal shim: re-route Tauri invoke to this dev bridge's /rpc.
  window.__TAURI_INTERNALS__ = window.__TAURI_INTERNALS__ || {};
  window.__TAURI_INTERNALS__.invoke = async function (cmd, args) {
    if (cmd === "rpc_call") {
      const r = await fetch("/rpc", {
        method: "POST",
        headers: {"content-type": "application/json"},
        body: JSON.stringify(args),
      });
      const data = await r.json();
      if (data.error) throw new Error(data.error.message);
      return data.result;
    }
    if (cmd === "open_in_os") {
      alert("open (dev bridge only simulates): " + args.path);
      return null;
    }
    throw new Error("unknown tauri command: " + cmd);
  };
  // Some Tauri APIs also check for this.
  window.__TAURI__ = window.__TAURI__ || {};
</script>
"""


class Handler(BaseHTTPRequestHandler):
    server_version = "Eoditdeora-dev"

    def log_message(self, fmt: str, *args) -> None:  # type: ignore[override]
        sys.stderr.write(f"[dev] {fmt % args}\n")

    def _serve_file(self, path: Path) -> None:
        if path.is_dir():
            path = path / "index.html"
        if not path.exists():
            self.send_error(404, "not found")
            return
        data = path.read_bytes()
        ext = path.suffix.lower()
        mime = {
            ".html": "text/html; charset=utf-8",
            ".js": "application/javascript; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".json": "application/json",
            ".svg": "image/svg+xml",
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".webp": "image/webp",
            ".ico": "image/x-icon",
        }.get(ext, "application/octet-stream")
        if ext == ".html":
            data = data.replace(b"<head>", b"<head>" + SHIM, 1)
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # noqa: N802
        rel = self.path.lstrip("/").split("?", 1)[0]
        if not rel:
            rel = "index.html"
        target = (BUILD / rel).resolve()
        # SPA fallback: any non-existent path → index.html
        if not target.exists() and target.is_relative_to(BUILD):
            target = BUILD / "index.html"
        if not target.is_relative_to(BUILD):
            self.send_error(403, "forbidden")
            return
        self._serve_file(target)

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/rpc":
            self.send_error(404)
            return
        length = int(self.headers.get("content-length", 0))
        body = self.rfile.read(length)
        try:
            req = json.loads(body)
        except json.JSONDecodeError:
            self.send_error(400)
            return
        msg = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": req.get("method"),
            "params": req.get("params") or {},
        }
        response = asyncio.run(self.server.rpc.handle_single(msg))  # type: ignore[attr-defined]
        out = json.dumps(response or {}, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)


def main() -> int:
    if not BUILD.exists():
        print("error: run `pnpm --filter eoditdeora-ui build` first", file=sys.stderr)
        return 2
    port = int(os.environ.get("EDDR_DEV_PORT", "7117"))
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    httpd.rpc = RpcServer()  # type: ignore[attr-defined]
    print(f"어딨더라 dev bridge → http://127.0.0.1:{port}")
    print("Ctrl-C to stop.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
