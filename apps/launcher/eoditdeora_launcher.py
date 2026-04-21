"""어딨더라 desktop launcher — production entry point.

This script is what the AppImage / MSI actually runs. It performs the
one-time setup the user needs on first launch, wires the indexer daemon,
brings up the local LLM backends, registers boot autostart, and then
hands control to the PyQt6 WebEngine window rendering the Svelte UI.

Flags:
  --autostart   launched by the OS on user login. Silences onboarding
                banners and skips any UI that needs explicit user click.
  --headless    start the HTTP bridge only; do not open a window. Used
                when someone just wants the service alive in the tray.

Environment:
  EODITDEORA_HOME   override the profile dir (same as the sidecar).
  EDDR_DEV_PORT     override the bridge port (default 7117).
"""

from __future__ import annotations

import argparse
import os
import sys
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path


def _resource_root() -> Path:
    """Where bundled resources live.

    * PyInstaller onefile: sys._MEIPASS
    * PyInstaller onedir:  parent of sys.executable
    * Dev:                 repo root
    """
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass)
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent.parent


ROOT = _resource_root()
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT / "scripts"))

# Force Qt backend — it's the only one our AppImage bundles.
os.environ["PYWEBVIEW_GUI"] = "qt"


def main() -> int:
    parser = argparse.ArgumentParser(prog="eoditdeora")
    parser.add_argument("--autostart", action="store_true",
                        help="Launched by OS autostart; skip onboarding UI.")
    parser.add_argument("--headless", action="store_true",
                        help="Run only the local service (no window).")
    parser.add_argument("--port", type=int,
                        default=int(os.environ.get("EDDR_DEV_PORT", "7117")))
    args = parser.parse_args()

    from eoditdeora.utils.logging import configure_logging, get_logger

    configure_logging()
    log = get_logger("eoditdeora.launcher")

    # ---- bring up local services ----------------------------------------

    # Indexer daemon — watches the registered roots.
    from eoditdeora.indexer.daemon import get_daemon

    get_daemon().start()
    log.info("indexer_daemon_up")

    # LLM runtime — start in a background thread so the UI can open even
    # while model weights are still warming up.
    def _ensure_llm() -> None:
        try:
            from eoditdeora.runtime.supervisor import RuntimeSupervisor

            states = RuntimeSupervisor().ensure_running()
            log.info("llm_ensure_ran", states=states)
        except Exception as e:  # noqa: BLE001
            log.warning("llm_ensure_failed", error=str(e))

    threading.Thread(target=_ensure_llm, name="eddr-llm-init", daemon=True).start()

    # First-run: enable OS autostart so the user never has to remember.
    try:
        from eoditdeora.runtime.autostart import enable, status

        if not status().get("enabled"):
            enable()
            log.info("autostart_registered")
    except Exception as e:  # noqa: BLE001
        log.warning("autostart_register_failed", error=str(e))

    # HTTP bridge (same one the dev script uses).
    from importlib import import_module

    dev = import_module("dev-server")
    build_dir = ROOT / "apps" / "ui" / "build"
    if not build_dir.exists():
        print(f"UI build missing at {build_dir}", file=sys.stderr)
        return 2
    # The Handler imports BUILD relative to the script file — when we
    # live inside PyInstaller onefile, sys._MEIPASS holds the right path.
    dev.BUILD = build_dir  # type: ignore[attr-defined]

    httpd = ThreadingHTTPServer(("127.0.0.1", args.port), dev.Handler)
    httpd.rpc = dev.RpcServer()  # type: ignore[attr-defined]
    threading.Thread(
        target=httpd.serve_forever, name="eddr-bridge", daemon=True
    ).start()
    log.info("bridge_listening", port=args.port)

    if args.headless:
        log.info("headless_mode_running")
        try:
            threading.Event().wait()
        except KeyboardInterrupt:
            pass
        finally:
            get_daemon().stop()
            httpd.shutdown()
        return 0

    # ---- open native window ---------------------------------------------

    import webview

    webview.create_window(
        "어딨더라",
        f"http://127.0.0.1:{args.port}/",
        width=960,
        height=680,
        min_size=(640, 420),
        resizable=True,
        text_select=True,
    )
    try:
        webview.start(gui="qt", debug=False)
    finally:
        log.info("window_closed_shutting_down")
        get_daemon().stop()
        httpd.shutdown()

    return 0


if __name__ == "__main__":
    sys.exit(main())
