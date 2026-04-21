"""Process supervisor for llama.cpp servers.

We spawn three `llama-server` processes on localhost, each with its own
GGUF and port. The supervisor is intentionally dumb: spawn, health poll,
stop. It does NOT restart automatically — if a backend dies, the RPC
layer surfaces that to the UI and the user re-enables it.

The llama.cpp binary location is resolved via (in order):
  * `EODITDEORA_LLAMA_SERVER` env var
  * PATH lookup for `llama-server`
  * runtimes/llama_cpp/bin/llama-server inside AppPaths.runtime

Models are looked up under AppPaths.models / `<model_id>.gguf`.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

from eoditdeora.config import load_settings
from eoditdeora.config.paths import get_paths
from eoditdeora.utils.logging import get_logger

log = get_logger(__name__)


@dataclass
class BackendConfig:
    name: str
    model_id: str
    port: int
    kind: str  # "chat" | "embed" | "rerank"
    extra_args: tuple[str, ...] = ()


class RuntimeSupervisor:
    def __init__(self) -> None:
        settings = load_settings()
        m = settings.model
        self._host = m.llama_cpp_host
        self._configs = [
            BackendConfig(
                name="llm",
                model_id=m.llm_model_id,
                port=m.llama_cpp_llm_port,
                kind="chat",
                extra_args=("--ctx-size", str(m.llm_context_tokens)),
            ),
            BackendConfig(
                name="embed",
                model_id=m.embedding_model_id,
                port=m.llama_cpp_embed_port,
                kind="embed",
                extra_args=("--embeddings",),
            ),
            BackendConfig(
                name="rerank",
                model_id=m.reranker_model_id,
                port=m.llama_cpp_rerank_port,
                kind="rerank",
                extra_args=("--reranking",),
            ),
        ]
        self._procs: dict[str, subprocess.Popen[bytes]] = {}
        self._lock = threading.Lock()

    def _llama_server_bin(self) -> Path | None:
        env = os.environ.get("EODITDEORA_LLAMA_SERVER")
        if env and Path(env).exists():
            return Path(env)
        which = shutil.which("llama-server")
        if which:
            return Path(which)
        bundled = get_paths().runtime / "bin" / ("llama-server.exe" if os.name == "nt" else "llama-server")
        if bundled.exists():
            return bundled
        return None

    def _model_path(self, model_id: str, quant: str = "Q8_0") -> Path:
        return get_paths().models / f"{model_id}.{quant}.gguf"

    def start_all(self) -> None:
        with self._lock:
            for cfg in self._configs:
                if cfg.name in self._procs:
                    continue
                self._spawn(cfg)

    def _spawn(self, cfg: BackendConfig) -> None:
        binary = self._llama_server_bin()
        if binary is None:
            log.error(
                "llama_server_not_found",
                hint="Set EODITDEORA_LLAMA_SERVER or install llama.cpp",
            )
            return
        settings = load_settings()
        quant = {
            "llm": settings.model.llm_quant,
            "embed": settings.model.embedding_quant,
            "rerank": settings.model.reranker_quant,
        }[cfg.name]
        model_path = self._model_path(cfg.model_id, quant)
        if not model_path.exists():
            log.warning(
                "model_weights_missing",
                backend=cfg.name,
                path=str(model_path),
                hint="Run `eddr models pull` once models are downloaded on first run.",
            )
            return
        cmd = [
            str(binary),
            "--model", str(model_path),
            "--host", self._host,
            "--port", str(cfg.port),
            "--n-gpu-layers", "999",
            "--flash-attn",
            *cfg.extra_args,
        ]
        log.info("spawn_backend", backend=cfg.name, port=cfg.port, model=cfg.model_id)
        self._procs[cfg.name] = subprocess.Popen(  # noqa: S603
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
        )

    def wait_healthy(self, backend: str, timeout: float = 120.0) -> bool:
        cfg = next((c for c in self._configs if c.name == backend), None)
        if cfg is None:
            return False
        url = f"http://{self._host}:{cfg.port}/health"
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                r = httpx.get(url, timeout=2.0)
                if r.status_code == 200:
                    return True
            except httpx.HTTPError:
                pass
            time.sleep(0.5)
        return False

    def stop_all(self) -> None:
        with self._lock:
            for name, proc in list(self._procs.items()):
                try:
                    proc.terminate()
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()
                except Exception as e:  # noqa: BLE001
                    log.debug("stop_backend_error", name=name, error=str(e))
            self._procs.clear()

    def is_running(self, backend: str) -> bool:
        p = self._procs.get(backend)
        return p is not None and p.poll() is None

    def ensure_running(self) -> dict[str, bool]:
        """Bring up any backend that isn't already alive.

        Used by the desktop launcher on startup (including boot autostart)
        so users never have to hand-start the LLM. Returns a map of
        backend → is_running after the attempt.
        """
        self.start_all()
        return {c.name: self.is_running(c.name) for c in self._configs}

    def port(self, backend: str) -> int:
        return next(c.port for c in self._configs if c.name == backend)

    @property
    def host(self) -> str:
        return self._host
