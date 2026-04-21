"""First-run bootstrap."""

from __future__ import annotations

from pathlib import Path

import pytest

from eoditdeora.api.methods import _first_run_bootstrap
from eoditdeora.config import load_settings
from eoditdeora.runtime import auto_connect as auto_connect_mod
from eoditdeora.runtime import autostart as autostart_mod


@pytest.fixture(autouse=True)
def _stub_auto_connect(monkeypatch: pytest.MonkeyPatch):
    """Isolate bootstrap tests from whatever LLM servers happen to be
    running on this machine. The idempotency/skips invariants are about
    the bootstrap itself, not about host-port discovery noise."""
    monkeypatch.setattr(
        auto_connect_mod,
        "auto_connect",
        lambda force=False: {"probed": 0, "actions": [], "roles": {}},
    )


@pytest.mark.asyncio
async def test_bootstrap_registers_documents_if_present(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    fake_home = tmp_path / "home"
    (fake_home / "Documents").mkdir(parents=True)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setattr(autostart_mod.sys, "platform", "linux")

    result = await _first_run_bootstrap({})
    assert any("added_root" in a for a in result["actions"])
    assert any("autostart_enabled" in a for a in result["actions"])
    # Autostart desktop file should exist.
    assert (tmp_path / "config" / "autostart" / "eoditdeora.desktop").exists()
    # Root persisted.
    assert str((fake_home / "Documents").resolve()) in load_settings().index.roots


@pytest.mark.asyncio
async def test_bootstrap_is_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    fake_home = tmp_path / "home"
    (fake_home / "Documents").mkdir(parents=True)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setattr(autostart_mod.sys, "platform", "linux")

    await _first_run_bootstrap({})
    second = await _first_run_bootstrap({})
    # Second call should take no extra actions.
    assert second["actions"] == []
    # Root count stays at 1.
    roots = load_settings().index.roots
    assert roots.count(str((fake_home / "Documents").resolve())) == 1


@pytest.mark.asyncio
async def test_bootstrap_skips_missing_documents_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    # Home exists, but Documents does not.
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setattr(autostart_mod.sys, "platform", "linux")
    result = await _first_run_bootstrap({})
    assert not any("added_root" in a for a in result["actions"])
    assert load_settings().index.roots == []
