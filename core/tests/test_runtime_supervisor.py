"""Supervisor tests — focused on binary resolution + spawn argument
construction, not on actually launching llama.cpp.

We monkeypatch `subprocess.Popen` and `shutil.which` to assert the
commands we would issue are correct.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from eoditdeora.runtime import supervisor as sup_mod
from eoditdeora.runtime.supervisor import RuntimeSupervisor


class FakePopen:
    instances: list["FakePopen"] = []

    def __init__(self, cmd, **kwargs):  # type: ignore[no-untyped-def]
        self.cmd = cmd
        self.kwargs = kwargs
        self._returncode: int | None = None
        FakePopen.instances.append(self)

    def poll(self) -> int | None:
        return self._returncode

    def terminate(self) -> None:
        self._returncode = 0

    def kill(self) -> None:
        self._returncode = -9

    def wait(self, timeout: float | None = None) -> int:  # noqa: ARG002
        if self._returncode is None:
            self._returncode = 0
        return self._returncode


@pytest.fixture(autouse=True)
def _clean():
    FakePopen.instances.clear()
    yield


def test_spawn_builds_expected_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    # Stage a fake llama-server binary we can find via env var.
    bin_path = tmp_path / "llama-server"
    bin_path.write_bytes(b"#!/bin/sh\nexit 0\n")
    bin_path.chmod(0o755)
    monkeypatch.setenv("EODITDEORA_LLAMA_SERVER", str(bin_path))

    # Pre-seed model files so supervisor thinks weights are present.
    from eoditdeora.config.paths import get_paths

    models = get_paths().models
    for name in (
        "gemma-4-26b-a4b-it.Q8_0.gguf",
        "bge-m3.Q8_0.gguf",
        "bge-reranker-v2-m3.Q8_0.gguf",
    ):
        (models / name).write_bytes(b"0")

    monkeypatch.setattr(sup_mod.subprocess, "Popen", FakePopen)

    sup = RuntimeSupervisor()
    sup.start_all()

    assert len(FakePopen.instances) == 3
    cmds = [" ".join(str(a) for a in p.cmd) for p in FakePopen.instances]
    assert any("--embeddings" in c for c in cmds)
    assert any("--reranking" in c for c in cmds)
    assert any("--ctx-size 32768" in c for c in cmds)
    # host/port hardcoded to 127.0.0.1 per D4
    assert all("127.0.0.1" in c for c in cmds)


def test_is_running_reflects_popen_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    bin_path = tmp_path / "llama-server"
    bin_path.write_bytes(b"x")
    bin_path.chmod(0o755)
    monkeypatch.setenv("EODITDEORA_LLAMA_SERVER", str(bin_path))
    from eoditdeora.config.paths import get_paths

    for name in (
        "gemma-4-26b-a4b-it.Q8_0.gguf",
        "bge-m3.Q8_0.gguf",
        "bge-reranker-v2-m3.Q8_0.gguf",
    ):
        (get_paths().models / name).write_bytes(b"0")

    monkeypatch.setattr(sup_mod.subprocess, "Popen", FakePopen)
    sup = RuntimeSupervisor()
    sup.start_all()

    assert sup.is_running("llm") is True
    # Mark backend as terminated.
    FakePopen.instances[0]._returncode = 0
    assert sup.is_running("llm") is False


def test_missing_binary_logs_and_skips_spawn(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("EODITDEORA_LLAMA_SERVER", raising=False)
    monkeypatch.setattr(sup_mod.shutil, "which", lambda _: None)
    monkeypatch.setattr(sup_mod.subprocess, "Popen", FakePopen)
    sup = RuntimeSupervisor()
    sup.start_all()
    assert FakePopen.instances == []


def test_missing_model_weights_skips_backend(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    bin_path = tmp_path / "llama-server"
    bin_path.write_bytes(b"x")
    bin_path.chmod(0o755)
    monkeypatch.setenv("EODITDEORA_LLAMA_SERVER", str(bin_path))
    # Do NOT create any .gguf files.
    monkeypatch.setattr(sup_mod.subprocess, "Popen", FakePopen)

    sup = RuntimeSupervisor()
    sup.start_all()
    # All three backends should be skipped.
    assert FakePopen.instances == []


def test_ports_are_unique_by_backend():
    sup = RuntimeSupervisor()
    ports = {sup.port("llm"), sup.port("embed"), sup.port("rerank")}
    assert len(ports) == 3
