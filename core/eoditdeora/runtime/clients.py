"""HTTP clients for external OpenAI-compatible inference servers.

Each client is built from an `EndpointConfig`. Eoditdeora does not
spawn any model weights — the user operates the backing server on
their own schedule (systemd, compose, manual), and we simply speak
its API. Constructors accept either a full config object or, for
backwards compatibility with the test suite, host+port arguments.

Factory helpers load the active configuration and return `None` when
a role is not configured, so callers short-circuit gracefully.
"""

from __future__ import annotations

from typing import Any

import httpx

from eoditdeora.config import load_settings
from eoditdeora.config.settings import EndpointConfig
from eoditdeora.runtime.endpoints import (
    resolve_chat_url,
    resolve_embeddings_url,
    resolve_rerank_url,
)
from eoditdeora.utils.logging import get_logger

log = get_logger(__name__)


def _auth_headers(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}"} if api_key else {}


def _coerce_endpoint(
    endpoint_or_host: EndpointConfig | str,
    port: int | None = None,
    *,
    api_key: str = "",
    model_id: str = "",
) -> EndpointConfig:
    """Accept either an EndpointConfig or legacy host/port pair.

    The legacy signature exists for tests that predate the endpoint
    refactor; it constructs a best-effort EndpointConfig from the pair.
    """
    if isinstance(endpoint_or_host, EndpointConfig):
        return endpoint_or_host
    if port is None:
        raise TypeError("port is required when a raw host is given")
    return EndpointConfig(
        base_url=f"http://{endpoint_or_host}:{port}",
        api_key=api_key,
        model_id=model_id,
    )


class _EndpointClient:
    """Base HTTP wrapper keyed on one configured role."""

    def __init__(
        self,
        endpoint_or_host: EndpointConfig | str,
        port: int | None = None,
        timeout: float = 60.0,
    ) -> None:
        endpoint = _coerce_endpoint(endpoint_or_host, port)
        if not endpoint.base_url:
            raise ValueError("endpoint is not configured")
        self._endpoint = endpoint
        self._client = httpx.Client(
            timeout=timeout, headers=_auth_headers(endpoint.api_key)
        )

    def close(self) -> None:
        self._client.close()


class LlmClient(_EndpointClient):
    def chat(
        self,
        system: str,
        user: str,
        *,
        temperature: float = 0.2,
        max_tokens: int = 1024,
        stop: list[str] | None = None,
        response_format: dict[str, Any] | None = None,
    ) -> str:
        body: dict[str, Any] = {
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if self._endpoint.model_id:
            body["model"] = self._endpoint.model_id
        if stop:
            body["stop"] = stop
        if response_format:
            body["response_format"] = response_format
        r = self._client.post(resolve_chat_url(self._endpoint), json=body)
        r.raise_for_status()
        data = r.json()
        return str(data["choices"][0]["message"]["content"])


class EmbedClient(_EndpointClient):
    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        body: dict[str, Any] = {"input": texts}
        if self._endpoint.model_id:
            body["model"] = self._endpoint.model_id
        r = self._client.post(resolve_embeddings_url(self._endpoint), json=body)
        r.raise_for_status()
        data = r.json()
        return [item["embedding"] for item in data["data"]]


class RerankClient(_EndpointClient):
    def rerank(
        self,
        query: str,
        docs: list[str],
        top_k: int | None = None,
    ) -> list[dict[str, Any]]:
        body: dict[str, Any] = {"query": query, "documents": docs}
        if self._endpoint.model_id:
            body["model"] = self._endpoint.model_id
        if top_k is not None:
            body["top_n"] = top_k
        r = self._client.post(resolve_rerank_url(self._endpoint), json=body)
        r.raise_for_status()
        data = r.json()
        return [
            {"index": int(x["index"]), "score": float(x["relevance_score"])}
            for x in data.get("results", [])
        ]


# ---- factories -----------------------------------------------------------


def get_llm_client() -> LlmClient | None:
    endpoint = load_settings().model.llm
    if not endpoint.base_url:
        return None
    return LlmClient(endpoint)


def get_embed_client() -> EmbedClient | None:
    endpoint = load_settings().model.embed
    if not endpoint.base_url:
        return None
    return EmbedClient(endpoint)


def get_rerank_client() -> RerankClient | None:
    endpoint = load_settings().model.rerank
    if not endpoint.base_url:
        return None
    return RerankClient(endpoint)
