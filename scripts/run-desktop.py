#!/usr/bin/env python3
"""어딨더라 native desktop launcher (dev).

This is a temporary runner that gives the same "real desktop app"
experience as the Tauri shell, without requiring the Rust toolchain
and GTK/WebKit build dependencies. It:

  1. spawns the HTTP bridge (`dev-server.py`) on 127.0.0.1 inside this
     process,
  2. opens a single PyQt6 WebEngine window pointed at the bridge,
  3. shuts the bridge down cleanly when the window closes.

Production ships the Tauri build; this script exists to unblock
development on machines without Rust/WebKit-dev headers.
"""

from __future__ import annotations

import os
import sys
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT / "scripts"))
os.environ.setdefault("EODITDEORA_HOME", str(ROOT / ".demo-home"))

# Force Qt backend (we have PyQt6 + WebEngine installed).
os.environ["PYWEBVIEW_GUI"] = "qt"

import webview  # noqa: E402

# Reuse the bridge handler we already built.
from importlib import import_module as _imp  # noqa: E402

_dev = _imp("dev_server")  # scripts/dev_server.py

from eoditdeora.indexer.daemon import get_daemon  # noqa: E402


def _start_bridge(port: int) -> ThreadingHTTPServer:
    httpd = ThreadingHTTPServer(("127.0.0.1", port), _dev.Handler)
    httpd.rpc = _dev.RpcServer()  # type: ignore[attr-defined]
    thread = threading.Thread(target=httpd.serve_forever, name="eddr-bridge", daemon=True)
    thread.start()
    return httpd


def main() -> int:
    build = ROOT / "apps" / "ui" / "build"
    if not build.exists():
        print("error: run `pnpm --filter eoditdeora-ui build` first", file=sys.stderr)
        return 2

    port = int(os.environ.get("EDDR_DEV_PORT", "7117"))
    bridge = _start_bridge(port)

    # Launch the indexer daemon up front so opening the window and then
    # immediately typing a query returns fresh results.
    get_daemon().start()

    title = "어딨더라"
    url = f"http://127.0.0.1:{port}/"

    # Svelte UI itself renders the spotlight; we just host it.
    webview.create_window(
        title,
        url,
        width=960,
        height=680,
        min_size=(640, 420),
        resizable=True,
        text_select=True,
    )

    try:
        webview.start(gui="qt", debug=False)
    finally:
        get_daemon().stop()
        bridge.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
