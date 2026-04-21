"""Model download manager.

Three GGUF files land in AppPaths.models:
  * gemma-4-26b-a4b-it.Q8_0.gguf
  * bge-m3.Q8_0.gguf
  * bge-reranker-v2-m3.Q8_0.gguf

Each slot has a URL source (env override or default Hugging Face mirror),
a target file name, and a live download thread with progress polling.
When all three exist, we call `RuntimeSupervisor.ensure_running()` so
the UI does not have to.

Progress is polled — not streamed — because the JSON-RPC dispatcher we
built is request/response. The UI hits `models.status` every second
while downloads run.
"""

from __future__ import annotations

import hashlib
import os
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from eoditdeora.config import load_settings
from eoditdeora.config.paths import get_paths
from eoditdeora.utils.logging import get_logger

log = get_logger(__name__)


@dataclass
class Slot:
    key: str  # "llm" | "embed" | "rerank"
    display: str
    url_env: str
    default_url: str | None  # None means user MUST set the env var
    target_name: str  # file name under models/
    expected_bytes: int  # 0 when unknown
    # Live state — mutated inside the worker thread.
    downloaded_bytes: int = 0
    total_bytes: int = 0
    error: str | None = None
    finished: bool = False
    cancelled: bool = False
    started_at: float = 0.0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            present = (get_paths().models / self.target_name).exists()
            pct = 0.0
            if self.total_bytes > 0:
                pct = 100.0 * self.downloaded_bytes / self.total_bytes
            elif present and not self.started_at:
                pct = 100.0
            return {
                "key": self.key,
                "display": self.display,
                "target_path": str(get_paths().models / self.target_name),
                "present": present,
                "running": self.started_at > 0 and not self.finished and not self.cancelled,
                "downloaded_bytes": self.downloaded_bytes,
                "total_bytes": self.total_bytes,
                "percent": round(pct, 2),
                "error": self.error,
                "cancelled": self.cancelled,
                "finished": self.finished,
                "source_configured": self.default_url is not None
                or bool(os.environ.get(self.url_env)),
            }


# -------- Default registry --------------------------------------------------

# Default URLs are left empty because Eoditdeora does not ship with
# publisher-blessed GGUF hosts. Users set them through settings.toml
# or the corresponding env var. The UI download button is disabled
# until a source is configured.
_SLOTS: dict[str, Slot] = {
    "llm": Slot(
        key="llm",
        display="Gemma 4 26B A4B IT (Q8_0)",
        url_env="EODITDEORA_LLM_GGUF_URL",
        default_url=None,
        target_name="gemma-4-26b-a4b-it.Q8_0.gguf",
        expected_bytes=0,
    ),
    "embed": Slot(
        key="embed",
        display="bge-m3 (Q8_0)",
        url_env="EODITDEORA_EMBED_GGUF_URL",
        default_url=None,
        target_name="bge-m3.Q8_0.gguf",
        expected_bytes=0,
    ),
    "rerank": Slot(
        key="rerank",
        display="bge-reranker-v2-m3 (Q8_0)",
        url_env="EODITDEORA_RERANK_GGUF_URL",
        default_url=None,
        target_name="bge-reranker-v2-m3.Q8_0.gguf",
        expected_bytes=0,
    ),
}


# -------- Public API --------------------------------------------------------


def all_status() -> list[dict[str, object]]:
    return [s.snapshot() for s in _SLOTS.values()]


def status(key: str) -> dict[str, object]:
    if key not in _SLOTS:
        raise ValueError(f"unknown model slot: {key}")
    return _SLOTS[key].snapshot()


def start_download(key: str) -> dict[str, object]:
    slot = _SLOTS.get(key)
    if slot is None:
        raise ValueError(f"unknown model slot: {key}")
    with slot._lock:
        if slot.started_at > 0 and not slot.finished and not slot.cancelled:
            return slot.snapshot()
        slot.started_at = time.time()
        slot.error = None
        slot.cancelled = False
        slot.finished = False
        slot.downloaded_bytes = 0
        slot.total_bytes = 0
    thread = threading.Thread(target=_run_download, args=(slot,), daemon=True, name=f"eddr-dl:{key}")
    thread.start()
    return slot.snapshot()


def cancel_download(key: str) -> dict[str, object]:
    slot = _SLOTS.get(key)
    if slot is None:
        raise ValueError(f"unknown model slot: {key}")
    with slot._lock:
        slot.cancelled = True
    return slot.snapshot()


# -------- Implementation ----------------------------------------------------


def _resolve_url(slot: Slot) -> str | None:
    env = os.environ.get(slot.url_env)
    if env:
        return env
    # Settings override (future): settings.model.gguf_urls[slot.key]
    return slot.default_url


def _run_download(slot: Slot) -> None:
    url = _resolve_url(slot)
    if not url:
        with slot._lock:
            slot.error = f"source_not_configured ({slot.url_env})"
            slot.finished = True
        log.warning("download_source_missing", slot=slot.key, env=slot.url_env)
        return

    target = get_paths().models / slot.target_name
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".part")

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Eoditdeora/0.1"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            total = int(resp.headers.get("Content-Length") or 0)
            with slot._lock:
                slot.total_bytes = total
            sha = hashlib.sha256()
            last_flush = time.monotonic()
            with tmp.open("wb") as fp:
                while True:
                    if slot.cancelled:
                        raise RuntimeError("cancelled by user")
                    chunk = resp.read(1024 * 1024)
                    if not chunk:
                        break
                    fp.write(chunk)
                    sha.update(chunk)
                    with slot._lock:
                        slot.downloaded_bytes += len(chunk)
                    # Occasional fsync so partial files survive crashes.
                    now = time.monotonic()
                    if now - last_flush > 5:
                        fp.flush()
                        last_flush = now
        tmp.rename(target)
    except Exception as e:  # noqa: BLE001
        with slot._lock:
            slot.error = f"{type(e).__name__}: {e}"
            slot.finished = True
        try:
            tmp.unlink(missing_ok=True)
        except Exception:  # noqa: BLE001
            pass
        log.warning("download_failed", slot=slot.key, error=str(e))
        return

    with slot._lock:
        slot.finished = True
    log.info("download_finished", slot=slot.key, path=str(target))

    # If all three slots are present, nudge the supervisor so the user
    # goes from "downloading" to "answer mode ready" without clicking.
    try:
        all_present = all(
            (get_paths().models / s.target_name).exists() for s in _SLOTS.values()
        )
        if all_present:
            from eoditdeora.runtime.supervisor import RuntimeSupervisor

            log.info("all_models_present_starting_llm")
            RuntimeSupervisor().ensure_running()
    except Exception as e:  # noqa: BLE001
        log.warning("post_download_supervisor_start_failed", error=str(e))


def autoconfigure_defaults() -> None:
    """Hook the user's settings-configured URLs into the slot table.

    Called at launch by the desktop launcher so the UI reflects any
    URLs the user pasted into settings.
    """
    settings = load_settings()
    mapping = getattr(settings.model, "gguf_urls", None) or {}
    for key, url in mapping.items():
        if key in _SLOTS and url:
            _SLOTS[key].default_url = url
