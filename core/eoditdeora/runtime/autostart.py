"""OS-native autostart registration.

Installs a boot-time entry so Eoditdeora relaunches whenever the user
logs in. Every code path is idempotent: running `enable()` twice is the
same as running it once.

Linux:  ~/.config/autostart/eoditdeora.desktop  (XDG autostart spec)
Windows: HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run\\Eoditdeora
macOS:   ~/Library/LaunchAgents/ai.markr.eoditdeora.plist  (reserved)

The launcher command we register is the running executable — in
production that's the frozen desktop launcher bundled inside the
AppImage/MSI; in dev it's this very script with the right flags.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from eoditdeora.utils.logging import get_logger

log = get_logger(__name__)

_APP_ID = "ai.markr.eoditdeora"
_APP_NAME = "Eoditdeora"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def enable(exec_cmd: str | None = None) -> dict[str, str]:
    """Register the app to start automatically at user login."""
    cmd = exec_cmd or _current_launcher()
    if sys.platform == "win32":
        return _enable_windows(cmd)
    if sys.platform == "darwin":
        return _enable_macos(cmd)
    return _enable_linux(cmd)


def disable() -> dict[str, str]:
    if sys.platform == "win32":
        return _disable_windows()
    if sys.platform == "darwin":
        return _disable_macos()
    return _disable_linux()


def status() -> dict[str, object]:
    if sys.platform == "win32":
        return _status_windows()
    if sys.platform == "darwin":
        return _status_macos()
    return _status_linux()


# ---------------------------------------------------------------------------
# Launcher resolution
# ---------------------------------------------------------------------------


def _current_launcher() -> str:
    """Return the best-effort self-invoking command for boot launch.

    * AppImage runtime sets APPIMAGE to the absolute image path — prefer it
      so autostart survives image moves.
    * PyInstaller-frozen desktop launcher: sys.executable is the bundled
      binary itself. Use that.
    * Dev mode: `python scripts/run-desktop.py`.
    """
    appimage = os.environ.get("APPIMAGE")
    if appimage and Path(appimage).exists():
        return appimage
    if getattr(sys, "frozen", False):
        return sys.executable
    # Dev mode fallback
    script = Path(__file__).resolve().parents[3] / "scripts" / "run-desktop.py"
    return f'"{sys.executable}" "{script}"'


# ---------------------------------------------------------------------------
# Linux (XDG autostart)
# ---------------------------------------------------------------------------


def _linux_autostart_path() -> Path:
    base = Path(
        os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config")
    )
    return base / "autostart" / "eoditdeora.desktop"


def _enable_linux(cmd: str) -> dict[str, str]:
    target = _linux_autostart_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    desktop = (
        "[Desktop Entry]\n"
        f"Type=Application\n"
        f"Name={_APP_NAME}\n"
        "Comment=어딨더라 — local document knowledge base\n"
        f"Exec={_linux_exec_command(cmd)} --autostart\n"
        "Terminal=false\n"
        "Categories=Office;Utility;\n"
        "X-GNOME-Autostart-enabled=true\n"
        "X-KDE-autostart-after=panel\n"
        "StartupNotify=false\n"
    )
    target.write_text(desktop, encoding="utf-8")
    target.chmod(0o644)
    log.info("autostart_enabled_linux", path=str(target))
    return {"ok": "true", "platform": "linux", "path": str(target)}


def _disable_linux() -> dict[str, str]:
    target = _linux_autostart_path()
    removed = False
    if target.exists():
        target.unlink()
        removed = True
    return {
        "ok": "true",
        "platform": "linux",
        "removed": str(removed).lower(),
        "path": str(target),
    }


def _status_linux() -> dict[str, object]:
    target = _linux_autostart_path()
    return {
        "platform": "linux",
        "enabled": target.exists(),
        "path": str(target),
    }


def _linux_exec_command(cmd: str) -> str:
    """Quote bare paths with spaces for XDG desktop Exec lines.

    The desktop entry parser tokenizes on spaces, so a bare AppImage
    path like `/home/user/My Apps/eoditdeora.AppImage` must be wrapped.
    Commands that already contain explicit quoting (dev mode launcher)
    are preserved as-is.
    """
    if any(ch.isspace() for ch in cmd) and '"' not in cmd:
        escaped = cmd.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return cmd


# ---------------------------------------------------------------------------
# Windows (HKCU Run)
# ---------------------------------------------------------------------------


_WIN_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def _enable_windows(cmd: str) -> dict[str, str]:
    import winreg  # type: ignore[import-not-found]

    # Wrap in quotes for paths with spaces.
    value = cmd if cmd.startswith('"') else f'"{cmd}"'
    value = f'{value} --autostart'
    with winreg.OpenKey(
        winreg.HKEY_CURRENT_USER, _WIN_RUN_KEY, 0, winreg.KEY_SET_VALUE
    ) as key:
        winreg.SetValueEx(key, _APP_NAME, 0, winreg.REG_SZ, value)
    log.info("autostart_enabled_windows", value=value)
    return {"ok": "true", "platform": "windows", "value": value}


def _disable_windows() -> dict[str, str]:
    import winreg  # type: ignore[import-not-found]

    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, _WIN_RUN_KEY, 0, winreg.KEY_SET_VALUE
        ) as key:
            winreg.DeleteValue(key, _APP_NAME)
        removed = True
    except FileNotFoundError:
        removed = False
    return {
        "ok": "true",
        "platform": "windows",
        "removed": str(removed).lower(),
    }


def _status_windows() -> dict[str, object]:
    import winreg  # type: ignore[import-not-found]

    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, _WIN_RUN_KEY, 0, winreg.KEY_READ
        ) as key:
            value, _type = winreg.QueryValueEx(key, _APP_NAME)
        return {"platform": "windows", "enabled": True, "value": value}
    except FileNotFoundError:
        return {"platform": "windows", "enabled": False}


# ---------------------------------------------------------------------------
# macOS (reserved; LaunchAgent plist)
# ---------------------------------------------------------------------------


def _enable_macos(cmd: str) -> dict[str, str]:
    target = Path.home() / "Library" / "LaunchAgents" / f"{_APP_ID}.plist"
    target.parent.mkdir(parents=True, exist_ok=True)
    plist = f"""<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<!DOCTYPE plist PUBLIC \"-//Apple//DTD PLIST 1.0//EN\" \"http://www.apple.com/DTDs/PropertyList-1.0.dtd\">
<plist version=\"1.0\"><dict>
  <key>Label</key><string>{_APP_ID}</string>
  <key>ProgramArguments</key><array>
    <string>{cmd}</string>
    <string>--autostart</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><false/>
</dict></plist>
"""
    target.write_text(plist, encoding="utf-8")
    return {"ok": "true", "platform": "macos", "path": str(target)}


def _disable_macos() -> dict[str, str]:
    target = Path.home() / "Library" / "LaunchAgents" / f"{_APP_ID}.plist"
    removed = False
    if target.exists():
        target.unlink()
        removed = True
    return {"ok": "true", "platform": "macos", "removed": str(removed).lower()}


def _status_macos() -> dict[str, object]:
    target = Path.home() / "Library" / "LaunchAgents" / f"{_APP_ID}.plist"
    return {"platform": "macos", "enabled": target.exists(), "path": str(target)}
