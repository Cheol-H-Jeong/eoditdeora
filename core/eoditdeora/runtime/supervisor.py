"""Endpoint-aware runtime view.

This used to spawn `llama-server` processes; it no longer does. A user's
local LLM is served externally (vLLM, llama.cpp, Ollama, …) and the
Eoditdeora app only *selects* one of the already-running endpoints.
RuntimeSupervisor remains as the single entry point the rest of the
codebase uses to ask "is the LLM up?" and "what is its host/port?".

Backwards-compatible API:
  * `is_running(role)`  — truthy iff the configured endpoint responds.
  * `port(role)`        — parses the port out of the configured URL
                          for legacy callers.
  * `ensure_running()`  — no-op, returns the current health map. We
                          intentionally do NOT launch any processes.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any
from urllib.parse import urlparse

from eoditdeora.config import load_settings
from eoditdeora.runtime.endpoints import health_for
from eoditdeora.utils.logging import get_logger

log = get_logger(__name__)

_ROLES = ("llm", "embed", "rerank")


class RuntimeSupervisor:
    """Thin facade around the configured endpoints. No process spawning."""

    @property
    def host(self) -> str:
        # Kept for callers that still take `(host, port)` pairs.
        return "127.0.0.1"

    def is_running(self, role: str) -> bool:
        if role not in _ROLES:
            return False
        endpoint = getattr(load_settings().model, role)
        if not endpoint.base_url:
            return False
        health = health_for(endpoint, timeout=1.0)
        return bool(health.get("reachable"))

    def port(self, role: str) -> int:
        endpoint = getattr(load_settings().model, role)
        return _port_from_url(endpoint.base_url) or 0

    def ensure_running(self) -> dict[str, bool]:
        """No-op. Returns the same shape `start_all()` used to, but only
        reports whether each configured endpoint is reachable."""
        return {role: self.is_running(role) for role in _ROLES}

    def health(self) -> dict[str, Any]:
        settings = load_settings()
        return {
            role: {
                **health_for(getattr(settings.model, role), timeout=1.0),
                "base_url": getattr(settings.model, role).base_url,
                "model_id": getattr(settings.model, role).model_id,
            }
            for role in _ROLES
        }


def _port_from_url(url: str) -> int | None:
    if not url:
        return None
    try:
        p = urlparse(url)
    except ValueError:
        return None
    if p.port is not None:
        return p.port
    if p.scheme == "http":
        return 80
    if p.scheme == "https":
        return 443
    return None


@lru_cache(maxsize=1)
def _singleton() -> RuntimeSupervisor:
    return RuntimeSupervisor()
