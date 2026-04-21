"""Local inference endpoint discovery and health checking.

Eoditdeora does NOT host models itself. It talks to whatever the user
is already running on this machine — typically one of:

  * llama.cpp `llama-server` (OpenAI-compatible, default port 8080)
  * vLLM OpenAI server (default 8000, path /v1)
  * LM Studio local server (default 1234)
  * Ollama (native API on 11434, also OpenAI-compatible at /v1)
  * Any custom URL the user pastes in Settings.

This module provides:

  * `discover_local()` — probe the well-known ports and return every
    reachable server together with the list of model IDs it advertises.
  * `probe(base_url, api_key?)` — inspect a single URL. Shared by the
    discover loop and the user's manual "Test" button.
  * `health_for(endpoint)` — is the configured endpoint usable right
    now? Used by the sidebar badge and the retriever short-circuit.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from eoditdeora.config.settings import EndpointConfig
from eoditdeora.utils.logging import get_logger

log = get_logger(__name__)


# Well-known localhost ports we probe when the user hits "자동 탐색".
# Order matters: earlier entries are preferred in the UI list.
WELL_KNOWN_CANDIDATES: tuple[tuple[str, str], ...] = (
    ("http://127.0.0.1:8080", "openai"),   # llama.cpp default
    ("http://127.0.0.1:8000/v1", "openai"),  # vLLM
    ("http://127.0.0.1:1234/v1", "openai"),  # LM Studio
    ("http://127.0.0.1:11434/v1", "openai"),  # Ollama (OpenAI-compat)
    ("http://127.0.0.1:5000/v1", "openai"),  # KoboldAI / others
    ("http://127.0.0.1:17651", "openai"),  # Legacy Eoditdeora ports
    ("http://127.0.0.1:17652", "openai"),
    ("http://127.0.0.1:17653", "openai"),
)


@dataclass
class Probe:
    base_url: str
    api_kind: str
    reachable: bool
    models: list[str]
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "base_url": self.base_url,
            "api_kind": self.api_kind,
            "reachable": self.reachable,
            "models": list(self.models),
            "error": self.error,
        }


def probe(base_url: str, api_key: str = "", api_kind: str = "openai", timeout: float = 2.0) -> Probe:
    """Hit `{base_url}/models` (OpenAI convention) and return what we find.

    Never raises — callers expect a Probe back no matter what went wrong.
    """
    base_url = base_url.rstrip("/")
    if not base_url:
        return Probe(base_url=base_url, api_kind=api_kind, reachable=False, models=[], error="empty_url")

    headers: dict[str, str] = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    url = _models_url(base_url, api_kind)
    try:
        r = httpx.get(url, timeout=timeout, headers=headers)
    except httpx.HTTPError as e:
        return Probe(base_url=base_url, api_kind=api_kind, reachable=False, models=[], error=str(e))

    if r.status_code != 200:
        return Probe(
            base_url=base_url,
            api_kind=api_kind,
            reachable=False,
            models=[],
            error=f"http_{r.status_code}",
        )

    try:
        data = r.json()
    except ValueError:
        return Probe(base_url=base_url, api_kind=api_kind, reachable=True, models=[], error="non_json_body")

    models = _models_from_payload(data, api_kind)
    return Probe(base_url=base_url, api_kind=api_kind, reachable=True, models=models)


def discover_local(timeout: float = 1.5) -> list[Probe]:
    """Probe every well-known localhost port. Returns only the hits."""
    out: list[Probe] = []
    for base, kind in WELL_KNOWN_CANDIDATES:
        p = probe(base, api_kind=kind, timeout=timeout)
        if p.reachable:
            out.append(p)
    return out


def health_for(endpoint: EndpointConfig, timeout: float = 2.0) -> dict[str, Any]:
    """Return a compact health snapshot for one configured role."""
    if not endpoint.base_url:
        return {"configured": False, "reachable": False, "error": "not_configured", "models": []}
    p = probe(endpoint.base_url, api_key=endpoint.api_key, api_kind=endpoint.api_kind, timeout=timeout)
    return {
        "configured": True,
        "reachable": p.reachable,
        "error": p.error,
        "models": p.models,
        "active_model": endpoint.model_id or (p.models[0] if p.models else ""),
    }


def _models_url(base_url: str, api_kind: str) -> str:
    # Ollama's native API lives at /api/tags, everyone else uses OpenAI's /models.
    if api_kind == "ollama":
        return f"{base_url}/api/tags"
    # If the caller already included /v1 we don't add it again.
    if base_url.endswith("/v1"):
        return f"{base_url}/models"
    return f"{base_url}/v1/models"


def _models_from_payload(data: dict[str, Any], api_kind: str) -> list[str]:
    if api_kind == "ollama":
        # {"models":[{"name":"llama3:8b"}, ...]}
        return [str(m.get("name") or m.get("model") or "") for m in data.get("models", []) if m]
    # OpenAI-style: {"data":[{"id":"gpt-3.5-turbo"}, ...]}
    rows = data.get("data") or data.get("models") or []
    return [str(r.get("id") or r.get("name") or "") for r in rows if r]


def resolve_chat_url(endpoint: EndpointConfig) -> str:
    base = endpoint.base_url.rstrip("/")
    if base.endswith("/v1"):
        return f"{base}/chat/completions"
    return f"{base}/v1/chat/completions"


def resolve_embeddings_url(endpoint: EndpointConfig) -> str:
    base = endpoint.base_url.rstrip("/")
    if base.endswith("/v1"):
        return f"{base}/embeddings"
    return f"{base}/v1/embeddings"


def resolve_rerank_url(endpoint: EndpointConfig) -> str:
    # Only llama.cpp's `/v1/rerank` is widely deployed for reranking over
    # OpenAI-ish hosts. vLLM/Ollama have no rerank endpoint; if the user
    # selects one of those as the rerank role, the call will 404 and the
    # retriever will fall back to fusion scoring alone.
    base = endpoint.base_url.rstrip("/")
    if base.endswith("/v1"):
        return f"{base}/rerank"
    return f"{base}/v1/rerank"
