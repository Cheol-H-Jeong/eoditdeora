"""Autostart registration.

Covers the Linux XDG path only — Windows and macOS write to system-
owned locations we cannot safely touch during unit tests.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from eoditdeora.runtime import autostart as autostart_mod


@pytest.fixture
def _linux_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setattr(autostart_mod.sys, "platform", "linux")
    yield tmp_path / "config" / "autostart" / "eoditdeora.desktop"


def test_enable_writes_desktop_file(_linux_home, monkeypatch):
    result = autostart_mod.enable(exec_cmd="/opt/eoditdeora.AppImage")
    assert result["ok"] == "true"
    assert _linux_home.exists()
    content = _linux_home.read_text(encoding="utf-8")
    assert "Type=Application" in content
    assert "Name=Eoditdeora" in content
    assert "Exec=/opt/eoditdeora.AppImage --autostart" in content


def test_enable_quotes_linux_exec_path_with_spaces(_linux_home):
    autostart_mod.enable(exec_cmd="/opt/My Apps/eoditdeora.AppImage")
    content = _linux_home.read_text(encoding="utf-8")
    assert 'Exec="/opt/My Apps/eoditdeora.AppImage" --autostart' in content


def test_enable_is_idempotent(_linux_home):
    autostart_mod.enable(exec_cmd="/opt/x")
    autostart_mod.enable(exec_cmd="/opt/x")
    assert _linux_home.exists()


def test_status_reflects_enabled(_linux_home):
    assert autostart_mod.status()["enabled"] is False
    autostart_mod.enable(exec_cmd="/opt/x")
    assert autostart_mod.status()["enabled"] is True


def test_disable_removes_file(_linux_home):
    autostart_mod.enable(exec_cmd="/opt/x")
    assert _linux_home.exists()
    autostart_mod.disable()
    assert not _linux_home.exists()


def test_disable_on_missing_is_noop(_linux_home):
    result = autostart_mod.disable()
    assert result["ok"] == "true"
    assert result["removed"] == "false"


def test_current_launcher_prefers_appimage_env(monkeypatch, tmp_path):
    img = tmp_path / "fake.AppImage"
    img.write_bytes(b"\x7fELF")
    monkeypatch.setenv("APPIMAGE", str(img))
    assert autostart_mod._current_launcher() == str(img)


def test_current_launcher_falls_back_to_dev_script(monkeypatch):
    monkeypatch.delenv("APPIMAGE", raising=False)
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    cmd = autostart_mod._current_launcher()
    assert "run-desktop.py" in cmd


def test_linux_exec_command_preserves_prequoted_dev_command():
    cmd = '"/usr/bin/python3" "/tmp/my repo/scripts/run-desktop.py"'
    assert autostart_mod._linux_exec_command(cmd) == cmd
