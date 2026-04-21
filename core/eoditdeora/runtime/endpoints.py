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
    ("http://127.0.0.1:8081", "openai"),   # llama-server role split: LLM
    ("http://127.0.0.1:8082", "openai"),   # llama-server role split: embed
    ("http://127.0.0.1:8083", "openai"),   # llama-server role split: rerank
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
    """Check that the endpoint is *actually usable* for inference.

    Two-step check:
      1. GET `{base_url}/models` (OpenAI convention) to enumerate models
         and confirm the server is alive.
      2. Issue a minimal POST against `{base_url}/chat/completions` to
         verify authentication. llama-server's `--api-key` gates chat but
         lets `/v1/models` through unauthenticated — so a models-only
         check produces a false-positive "healthy" badge. The second
         step classifies 401/403 as `auth_required` and 404 as
         `endpoint_not_found` so the UI can show a useful hint instead
         of a silent failure at first query.

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

    if r.status_code in (401, 403):
        return Probe(
            base_url=base_url,
            api_kind=api_kind,
            reachable=False,
            models=[],
            error="auth_required",
        )
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
        return Probe(base_url=base_url, api_kind=api_kind, reachable=False, models=[], error="non_json_body")

    models = _models_from_payload(data, api_kind)

    # Step 2: auth-aware chat probe. Ollama native has a different surface
    # and is validated via /api/tags listing alone, so we only do the auth
    # round-trip for the OpenAI-compatible kind. Use a longer deadline
    # than the models GET because cold large-model servers (e.g. 120B
    # MoE on Vulkan) can take several seconds to produce the first token
    # even when max_tokens=1. A premature timeout here would mis-flag
    # perfectly good endpoints as unreachable.
    if api_kind == "openai":
        auth_err = _auth_probe(base_url, headers, models, max(timeout * 4, 8.0))
        if auth_err is not None:
            return Probe(
                base_url=base_url,
                api_kind=api_kind,
                reachable=False,
                models=models,
                error=auth_err,
            )

    return Probe(base_url=base_url, api_kind=api_kind, reachable=True, models=models)


def _auth_probe(
    base_url: str,
    headers: dict[str, str],
    models: list[str],
    timeout: float,
) -> str | None:
    """Confirm that *some* inference route on the server accepts our creds.

    Most servers expose all three roles on the same base URL, so hitting
    `/chat/completions` with a 1-token request is enough. But dedicated
    embedding servers (HF TEI, `llama-server --embeddings`) do not
    implement `/chat/completions` at all and return 404 on it. Treating
    that as `endpoint_not_found` would mis-flag a perfectly good embed
    endpoint as unreachable, so we fall back to `/embeddings` when the
    chat route is missing. Only if both routes are missing do we conclude
    the URL is wrong. `auth_required` wins over `endpoint_not_found`
    across both attempts — a 401 from either arm is the actionable
    message.
    """
    chat_err = _probe_chat(base_url, headers, models, timeout)
    if chat_err is None:
        return None
    if chat_err == "auth_required":
        return "auth_required"
    if chat_err == "endpoint_not_found":
        # Server does not host chat. Maybe it's embed-only. Try that
        # before concluding the URL is wrong.
        embed_err = _probe_embeddings(base_url, headers, models, timeout)
        if embed_err is None:
            return None
        if embed_err == "auth_required":
            return "auth_required"
        # Both arms 404 → really the wrong URL.
        return chat_err
    return chat_err


def _probe_chat(
    base_url: str,
    headers: dict[str, str],
    models: list[str],
    timeout: float,
) -> str | None:
    body: dict[str, Any] = {
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 1,
        "temperature": 0.0,
        "stream": False,
    }
    if models:
        body["model"] = models[0]
    return _classify_auth_post(_chat_url_for_probe(base_url), body, headers, timeout)


def _probe_embeddings(
    base_url: str,
    headers: dict[str, str],
    models: list[str],
    timeout: float,
) -> str | None:
    body: dict[str, Any] = {"input": "ping"}
    if models:
        body["model"] = models[0]
    return _classify_auth_post(_embed_url_for_probe(base_url), body, headers, timeout)


def _classify_auth_post(
    url: str,
    body: dict[str, Any],
    headers: dict[str, str],
    timeout: float,
) -> str | None:
    try:
        r = httpx.post(url, json=body, headers=headers, timeout=timeout)
    except httpx.ReadTimeout:
        # Server accepted the TCP connection but did not reply in time.
        # Cold 100B-parameter servers behave this way on first token
        # even when max_tokens=1. Not a failure.
        return None
    except httpx.HTTPError as e:
        return str(e)
    if r.status_code in (401, 403):
        return "auth_required"
    if r.status_code == 404:
        return "endpoint_not_found"
    if r.status_code >= 500:
        return f"http_{r.status_code}"
    return None


def _chat_url_for_probe(base_url: str) -> str:
    base = base_url.rstrip("/")
    if base.endswith("/v1"):
        return f"{base}/chat/completions"
    return f"{base}/v1/chat/completions"


def _embed_url_for_probe(base_url: str) -> str:
    base = base_url.rstrip("/")
    if base.endswith("/v1"):
        return f"{base}/embeddings"
    return f"{base}/v1/embeddings"


def discover_local(timeout: float = 1.5) -> list[Probe]:
    """Probe every well-known localhost port.

    Returns any probe that either fully reached the server *or* got as
    far as listing models — the latter matters because an
    `auth_required` endpoint still has a model catalog the UI should
    surface (with a lock icon), even though auto_connect must not
    assign it. Fully-dead ports (no route, no models) stay filtered.
    """
    out: list[Probe] = []
    for base, kind in WELL_KNOWN_CANDIDATES:
        p = probe(base, api_kind=kind, timeout=timeout)
        if p.reachable or p.models:
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
