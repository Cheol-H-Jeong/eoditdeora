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
import math
import time
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

from eoditdeora.api.rpc_server import (
    ERR_UPSTREAM_AUTH,
    ERR_UPSTREAM_BAD_REQUEST,
    ERR_UPSTREAM_BAD_RESPONSE,
    ERR_UPSTREAM_NOT_FOUND,
    ERR_UPSTREAM_RATE_LIMIT,
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

_MAX_UPSTREAM_ATTEMPTS = 3
_INITIAL_RETRY_DELAY_SEC = 0.2
_MAX_RETRY_DELAY_SEC = 1.0


def _extract_text_from_part(part: Any) -> str:
    if isinstance(part, str):
        return part
    if not isinstance(part, dict):
        return ""
    if isinstance(part.get("text"), str):
        return part["text"]
    if isinstance(part.get("content"), str):
        return part["content"]
    if isinstance(part.get("reasoning_content"), str):
        return part["reasoning_content"]
    if isinstance(part.get("reasoning"), str):
        return part["reasoning"]
    return ""


def _coerce_text_content(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "".join(_extract_text_from_part(part) for part in value)
    return ""


def _auth_headers(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}"} if api_key else {}


def _is_retryable_status(status_code: int) -> bool:
    return status_code == 429 or status_code >= 500


def _extract_error_detail(r: httpx.Response) -> str:
    try:
        payload = r.json()
    except (ValueError, TypeError):
        payload = None

    candidates: list[Any] = []
    if isinstance(payload, dict):
        error_payload = payload.get("error")
        if isinstance(error_payload, dict):
            candidates.extend(
                [
                    error_payload.get("message"),
                    error_payload.get("detail"),
                    error_payload.get("error"),
                    error_payload.get("code"),
                    error_payload.get("type"),
                ]
            )
        else:
            candidates.append(error_payload)
        candidates.extend(
            [
                payload.get("message"),
                payload.get("detail"),
                payload.get("error_description"),
                payload.get("error_msg"),
            ]
        )
    else:
        try:
            candidates.append(r.text)
        except Exception:  # noqa: BLE001
            pass

    for candidate in candidates:
        if candidate is None:
            continue
        text = str(candidate).strip()
        if text:
            return text
    return ""


def _truncate_detail(text: str, *, limit: int = 160) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1].rstrip() + "…"


def _extract_bad_response_detail(r: httpx.Response) -> str:
    content_type = r.headers.get("content-type", "").strip()
    snippet = ""
    try:
        snippet = _truncate_detail(r.text)
    except Exception:  # noqa: BLE001
        snippet = ""

    parts: list[str] = []
    if content_type:
        parts.append(f"content-type={content_type}")
    if snippet:
        parts.append(f"body={snippet}")
    return " | ".join(parts)


def _retry_delay_for_response(r: httpx.Response, default_delay: float) -> float:
    """Honor Retry-After when an upstream asks us to slow down.

    Servers commonly send either delta-seconds (`Retry-After: 2`) or an
    absolute HTTP date. We cap the result so one bad header cannot stall
    the UI for an arbitrarily long time.
    """
    headers = getattr(r, "headers", None)
    raw = ""
    if headers is not None:
        raw = str(headers.get("retry-after", "")).strip()
    if not raw:
        return default_delay
    try:
        delay = float(raw)
    except ValueError:
        try:
            retry_at = parsedate_to_datetime(raw)
        except (TypeError, ValueError, IndexError, OverflowError):
            return default_delay
        now = time.time()
        delay = retry_at.timestamp() - now
    if delay <= 0:
        return default_delay
    return min(delay, _MAX_RETRY_DELAY_SEC)


def _raise_bad_response(url: str, role: str, detail: str) -> None:
    data: dict[str, Any] = {"url": url, "role": role}
    normalized = detail.strip()
    if normalized:
        data["detail"] = normalized
    raise RpcError(
        ERR_UPSTREAM_BAD_RESPONSE,
        "추론 서버 응답 JSON 형식이 올바르지 않습니다",
        data,
    )


def _coerce_embedding_vector(url: str, idx: int, embedding: Any) -> list[float]:
    if not isinstance(embedding, list):
        _raise_bad_response(url, "embed", f"data[{idx}].embedding is missing")

    vector: list[float] = []
    for dim, raw_value in enumerate(embedding):
        if isinstance(raw_value, bool):
            _raise_bad_response(
                url,
                "embed",
                f"data[{idx}].embedding[{dim}] is not a finite number",
            )
        try:
            value = float(raw_value)
        except (TypeError, ValueError):
            _raise_bad_response(
                url,
                "embed",
                f"data[{idx}].embedding[{dim}] is not a finite number",
            )
        if not math.isfinite(value):
            _raise_bad_response(
                url,
                "embed",
                f"data[{idx}].embedding[{dim}] is not a finite number",
            )
        vector.append(value)
    return vector


def _bad_request_message(role: str, detail: str) -> str:
    role_label = {
        "llm": "답변",
        "embed": "임베딩",
        "rerank": "재정렬",
    }.get(role, "추론")
    normalized = detail.lower()
    if any(
        token in normalized
        for token in (
            "context length",
            "maximum context",
            "max context",
            "token limit",
            "too many tokens",
            "prompt is too long",
            "requested tokens",
            "maximum tokens",
        )
    ):
        return (
            f"{role_label} 서버가 요청 길이를 거부했습니다. "
            "질문을 더 짧게 하거나 검색 범위를 줄인 뒤 다시 시도하세요."
        )
    if any(
        token in normalized
        for token in (
            "model is required",
            "model_id",
            "model id",
            "unknown model",
            "no such model",
            "model_not_found",
            "model name",
        )
    ):
        return (
            f"{role_label} 서버의 모델 ID가 비어 있거나 올바르지 않습니다. "
            "설정에서 모델 ID를 확인하세요."
        )
    return (
        f"{role_label} 서버가 요청을 거부했습니다. "
        "모델 ID, 요청 형식, OpenAI 호환 API 설정을 확인하세요."
    )


def _extract_llm_message_text(data: dict[str, Any], url: str) -> str:
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        _raise_bad_response(url, "llm", "missing choices[]")

    first_choice = choices[0]
    if not isinstance(first_choice, dict):
        _raise_bad_response(url, "llm", "choices[0] is not an object")

    msg = first_choice.get("message")
    if not isinstance(msg, dict):
        _raise_bad_response(url, "llm", "choices[0].message is missing")

    # Reasoning models sometimes emit an empty `content` but keep the only
    # textual payload in a sibling reasoning field.
    content = _coerce_text_content(msg.get("content"))
    if not content:
        content = _coerce_text_content(
            msg.get("reasoning_content") or msg.get("reasoning")
        )
    if not content:
        _raise_bad_response(
            url,
            "llm",
            "choices[0].message has no usable content/reasoning text",
        )
    return str(content)


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
    detail = _extract_error_detail(r)
    if detail:
        data["detail"] = detail
    if r.status_code in (401, 403):
        raise RpcError(ERR_UPSTREAM_AUTH, "API 키가 필요하거나 유효하지 않습니다", data)
    if r.status_code == 404:
        raise RpcError(
            ERR_UPSTREAM_NOT_FOUND,
            "엔드포인트 경로 또는 모델 ID를 찾을 수 없습니다",
            data,
        )
    if r.status_code == 429:
        raise RpcError(
            ERR_UPSTREAM_RATE_LIMIT,
            "요청이 너무 많아 잠시 제한되었습니다",
            data,
        )
    if 400 <= r.status_code < 500:
        raise RpcError(
            ERR_UPSTREAM_BAD_REQUEST,
            _bad_request_message(role, detail),
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
    delay = _INITIAL_RETRY_DELAY_SEC
    for attempt in range(1, _MAX_UPSTREAM_ATTEMPTS + 1):
        try:
            r = client.post(url, json=body)
        except httpx.HTTPError as e:
            if attempt < _MAX_UPSTREAM_ATTEMPTS:
                log.warning(
                    "upstream_request_retry",
                    role=role,
                    url=url,
                    reason="transport_error",
                    detail=str(e),
                    attempt=attempt,
                    max_attempts=_MAX_UPSTREAM_ATTEMPTS,
                    delay_sec=delay,
                )
                time.sleep(delay)
                delay = min(delay * 2, _MAX_RETRY_DELAY_SEC)
                continue
            raise RpcError(
                ERR_UPSTREAM_UNAVAILABLE,
                "추론 서버에 연결할 수 없습니다",
                {"url": url, "role": role, "detail": str(e)},
            ) from e

        if r.status_code >= 400:
            if attempt < _MAX_UPSTREAM_ATTEMPTS and _is_retryable_status(r.status_code):
                retry_delay = _retry_delay_for_response(r, delay)
                log.warning(
                    "upstream_request_retry",
                    role=role,
                    url=url,
                    reason="http_status",
                    status=r.status_code,
                    attempt=attempt,
                    max_attempts=_MAX_UPSTREAM_ATTEMPTS,
                    delay_sec=retry_delay,
                )
                time.sleep(retry_delay)
                delay = min(delay * 2, _MAX_RETRY_DELAY_SEC)
                continue
            _raise_upstream_for_status(r, url, role)

        try:
            return r.json()  # type: ignore[no-any-return]
        except ValueError as e:
            data = {"url": url, "role": role}
            if detail := _extract_bad_response_detail(r):
                data["detail"] = detail
            raise RpcError(
                ERR_UPSTREAM_BAD_RESPONSE,
                "추론 서버가 JSON이 아닌 응답을 돌려주었습니다",
                data,
            ) from e

    raise AssertionError("unreachable")


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
        url = resolve_chat_url(self._endpoint)
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
        data = _post_json(self._client, url, body, role="llm")
        return _extract_llm_message_text(data, url)

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
        delay = _INITIAL_RETRY_DELAY_SEC
        yielded_any = False
        for attempt in range(1, _MAX_UPSTREAM_ATTEMPTS + 1):
            try:
                with httpx.stream(
                    "POST",
                    url,
                    json=body,
                    headers=_auth_headers(self._endpoint.api_key),
                    timeout=self._timeout,
                ) as r:
                    if r.status_code >= 400:
                        if (
                            attempt < _MAX_UPSTREAM_ATTEMPTS
                            and _is_retryable_status(r.status_code)
                        ):
                            retry_delay = _retry_delay_for_response(r, delay)
                            log.warning(
                                "upstream_stream_retry",
                                role="llm",
                                url=url,
                                reason="http_status",
                                status=r.status_code,
                                attempt=attempt,
                                max_attempts=_MAX_UPSTREAM_ATTEMPTS,
                                delay_sec=retry_delay,
                            )
                            time.sleep(retry_delay)
                            delay = min(delay * 2, _MAX_RETRY_DELAY_SEC)
                            continue
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
                            detail = _truncate_detail(payload)
                            data = {"url": url, "role": "llm"}
                            if detail:
                                data["detail"] = f"sse_chunk={detail}"
                            raise RpcError(
                                ERR_UPSTREAM_BAD_RESPONSE,
                                "추론 서버가 올바른 SSE JSON 청크를 돌려주지 않았습니다",
                                data,
                            ) from e
                        choices = data.get("choices") or []
                        if not choices:
                            continue
                        delta = choices[0].get("delta") or {}
                        content = _coerce_text_content(
                            delta.get("content")
                            or delta.get("reasoning_content")
                            or delta.get("reasoning")
                        )
                        if content:
                            yielded_any = True
                            yield str(content)
                    return
            except httpx.HTTPError as e:
                if not yielded_any and attempt < _MAX_UPSTREAM_ATTEMPTS:
                    log.warning(
                        "upstream_stream_retry",
                        role="llm",
                        url=url,
                        reason="transport_error",
                        detail=str(e),
                        attempt=attempt,
                        max_attempts=_MAX_UPSTREAM_ATTEMPTS,
                        delay_sec=delay,
                    )
                    time.sleep(delay)
                    delay = min(delay * 2, _MAX_RETRY_DELAY_SEC)
                    continue
                raise RpcError(
                    ERR_UPSTREAM_UNAVAILABLE,
                    "추론 서버에 연결할 수 없습니다",
                    {"url": url, "role": "llm", "detail": str(e)},
                ) from e

        raise AssertionError("unreachable")


class EmbedClient(_EndpointClient):
    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        url = resolve_embeddings_url(self._endpoint)
        body: dict[str, Any] = {"input": texts}
        if self._endpoint.model_id:
            body["model"] = self._endpoint.model_id
        data = _post_json(self._client, url, body, role="embed")
        items = data.get("data")
        if not isinstance(items, list):
            _raise_bad_response(url, "embed", "missing data[]")

        vectors: list[list[float]] = []
        for idx, item in enumerate(items):
            if not isinstance(item, dict):
                _raise_bad_response(url, "embed", f"data[{idx}] is not an object")
            embedding = item.get("embedding")
            vectors.append(_coerce_embedding_vector(url, idx, embedding))
        return vectors


class RerankClient(_EndpointClient):
    def rerank(
        self,
        query: str,
        docs: list[str],
        top_k: int | None = None,
    ) -> list[dict[str, Any]]:
        url = resolve_rerank_url(self._endpoint)
        body: dict[str, Any] = {"query": query, "documents": docs}
        if self._endpoint.model_id:
            body["model"] = self._endpoint.model_id
        if top_k is not None:
            body["top_n"] = top_k
        data = _post_json(self._client, url, body, role="rerank")
        raw_results = data.get("results")
        if not isinstance(raw_results, list):
            _raise_bad_response(url, "rerank", "missing results[]")

        results: list[dict[str, Any]] = []
        for idx, item in enumerate(raw_results):
            if not isinstance(item, dict):
                _raise_bad_response(url, "rerank", f"results[{idx}] is not an object")
            raw_index = item.get("index")
            raw_score = item.get("relevance_score")
            try:
                index = int(raw_index)
                score = float(raw_score)
            except (TypeError, ValueError):
                _raise_bad_response(
                    url,
                    "rerank",
                    f"results[{idx}] is missing numeric index/relevance_score",
                )
            results.append({"index": index, "score": score})
        return results


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
