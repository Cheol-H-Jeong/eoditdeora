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

import json
from typing import Any

import httpx

from eoditdeora.api.rpc_server import (
    ERR_UPSTREAM_AUTH,
    ERR_UPSTREAM_BAD_RESPONSE,
    ERR_UPSTREAM_NOT_FOUND,
    ERR_UPSTREAM_UNAVAILABLE,
    RpcError,
)
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


def _raise_upstream_for_status(r: httpx.Response, url: str, role: str) -> None:
    """Translate upstream HTTP errors into RpcError with helpful codes.

    The UI dispatches on the RPC error code to render the right
    remediation (e.g. "API 키가 필요합니다" vs "서버 응답 없음"), so
    the classification happens here rather than being flattened into a
    generic 'internal error' at the dispatcher.
    """
    if r.status_code < 400:
        return
    data: dict[str, Any] = {"url": url, "role": role, "status": r.status_code}
    if r.status_code in (401, 403):
        raise RpcError(ERR_UPSTREAM_AUTH, "API 키가 필요하거나 유효하지 않습니다", data)
    if r.status_code == 404:
        raise RpcError(
            ERR_UPSTREAM_NOT_FOUND,
            "엔드포인트 경로 또는 모델 ID를 찾을 수 없습니다",
            data,
        )
    if r.status_code >= 500:
        raise RpcError(
            ERR_UPSTREAM_UNAVAILABLE,
            f"추론 서버가 응답하지 않습니다 (HTTP {r.status_code})",
            data,
        )
    raise RpcError(
        ERR_UPSTREAM_UNAVAILABLE,
        f"추론 서버 오류 (HTTP {r.status_code})",
        data,
    )


def _post_json(
    client: httpx.Client,
    url: str,
    body: dict[str, Any],
    role: str,
) -> dict[str, Any]:
    try:
        r = client.post(url, json=body)
    except httpx.HTTPError as e:
        raise RpcError(
            ERR_UPSTREAM_UNAVAILABLE,
            "추론 서버에 연결할 수 없습니다",
            {"url": url, "role": role, "detail": str(e)},
        ) from e
    _raise_upstream_for_status(r, url, role)
    try:
        return r.json()  # type: ignore[no-any-return]
    except ValueError as e:
        raise RpcError(
            ERR_UPSTREAM_BAD_RESPONSE,
            "추론 서버가 JSON이 아닌 응답을 돌려주었습니다",
            {"url": url, "role": role},
        ) from e


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
        self._timeout = timeout
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
        data = _post_json(self._client, resolve_chat_url(self._endpoint), body, role="llm")
        choices = data.get("choices") or []
        if not choices:
            return ""
        msg = choices[0].get("message") or {}
        # Reasoning models (gpt-oss, o1-style) sometimes return an empty
        # `content` with the actual answer in a sibling `reasoning` field
        # when token budget is tight. Fall back to that rather than
        # surfacing an empty string to the retriever.
        content = msg.get("content") or ""
        # Different reasoning-model conventions: OpenAI o1 / gpt-oss use
        # `reasoning`, llama-server with Qwen reasoning uses
        # `reasoning_content`. Fall back to whichever is populated so
        # the caller doesn't silently receive an empty answer.
        if not content:
            content = msg.get("reasoning_content") or msg.get("reasoning") or ""
        return str(content)

    def chat_stream(
        self,
        system: str,
        user: str,
        *,
        temperature: float = 0.2,
        max_tokens: int = 1024,
        stop: list[str] | None = None,
        response_format: dict[str, Any] | None = None,
    ):
        body: dict[str, Any] = {
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }
        if self._endpoint.model_id:
            body["model"] = self._endpoint.model_id
        if stop:
            body["stop"] = stop
        if response_format:
            body["response_format"] = response_format

        url = resolve_chat_url(self._endpoint)
        try:
            with httpx.stream(
                "POST",
                url,
                json=body,
                headers=_auth_headers(self._endpoint.api_key),
                timeout=self._timeout,
            ) as r:
                _raise_upstream_for_status(r, url, "llm")
                for line in r.iter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    payload = line[5:].strip()
                    if payload == "[DONE]":
                        return
                    try:
                        data = json.loads(payload)
                    except ValueError as e:
                        raise RpcError(
                            ERR_UPSTREAM_BAD_RESPONSE,
                            "추론 서버가 올바른 SSE JSON 청크를 돌려주지 않았습니다",
                            {"url": url, "role": "llm"},
                        ) from e
                    choices = data.get("choices") or []
                    if not choices:
                        continue
                    delta = choices[0].get("delta") or {}
                    content = (
                        delta.get("content")
                        or delta.get("reasoning_content")
                        or delta.get("reasoning")
                        or ""
                    )
                    if content:
                        yield str(content)
        except httpx.HTTPError as e:
            raise RpcError(
                ERR_UPSTREAM_UNAVAILABLE,
                "추론 서버에 연결할 수 없습니다",
                {"url": url, "role": "llm", "detail": str(e)},
            ) from e


class EmbedClient(_EndpointClient):
    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        body: dict[str, Any] = {"input": texts}
        if self._endpoint.model_id:
            body["model"] = self._endpoint.model_id
        data = _post_json(
            self._client,
            resolve_embeddings_url(self._endpoint),
            body,
            role="embed",
        )
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
        data = _post_json(
            self._client,
            resolve_rerank_url(self._endpoint),
            body,
            role="rerank",
        )
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
