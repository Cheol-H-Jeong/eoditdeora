"""LLM runtime client tests using an in-process HTTP mock.

llama-server exposes OpenAI-compatible endpoints. We simulate them with
httpx.MockTransport so the client logic (request shape + response
parsing) is exercised without needing a real server.
"""

from __future__ import annotations

import json as _json

import httpx
import pytest

from eoditdeora.api.rpc_server import (
    ERR_UPSTREAM_AUTH,
    ERR_UPSTREAM_BAD_REQUEST,
    ERR_UPSTREAM_BAD_RESPONSE,
    ERR_UPSTREAM_NOT_FOUND,
    ERR_UPSTREAM_RATE_LIMIT,
    ERR_UPSTREAM_UNAVAILABLE,
    RpcError,
)
from eoditdeora.runtime.clients import EmbedClient, LlmClient, RerankClient


def _mock_client(handler) -> httpx.Client:
    transport = httpx.MockTransport(handler)
    return httpx.Client(base_url="http://127.0.0.1:0", transport=transport)


def test_llm_chat_returns_message_content(monkeypatch: pytest.MonkeyPatch):
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["json"] = _json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"role": "assistant", "content": "답변 본문"}}
                ]
            },
        )

    client = LlmClient("127.0.0.1", 0)
    client._client = _mock_client(handler)  # type: ignore[attr-defined]
    result = client.chat("시스템", "사용자", temperature=0.1, max_tokens=64)
    assert result == "답변 본문"
    assert captured["path"] == "/v1/chat/completions"
    assert captured["json"]["messages"][0]["role"] == "system"
    assert captured["json"]["temperature"] == 0.1


def test_llm_chat_sends_response_format_and_stop():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json as _json

        seen["json"] = _json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

    client = LlmClient("127.0.0.1", 0)
    client._client = _mock_client(handler)  # type: ignore[attr-defined]
    client.chat(
        "sys",
        "usr",
        stop=["END"],
        response_format={"type": "json_object"},
    )
    assert seen["json"]["stop"] == ["END"]
    assert seen["json"]["response_format"] == {"type": "json_object"}


def test_embed_client_parses_openai_response():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/embeddings"
        return httpx.Response(
            200,
            json={
                "data": [
                    {"embedding": [0.1, 0.2, 0.3]},
                    {"embedding": [0.4, 0.5, 0.6]},
                ]
            },
        )

    client = EmbedClient("127.0.0.1", 0)
    client._client = _mock_client(handler)  # type: ignore[attr-defined]
    vecs = client.embed(["가", "나"])
    assert vecs == [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]


def test_embed_client_malformed_json_raises_bad_response():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/embeddings"
        return httpx.Response(200, json={"data": [{"not_embedding": [0.1, 0.2]}]})

    client = EmbedClient("127.0.0.1", 0)
    client._client = _mock_client(handler)  # type: ignore[attr-defined]
    with pytest.raises(RpcError) as ei:
        client.embed(["가"])
    assert ei.value.code == ERR_UPSTREAM_BAD_RESPONSE
    assert ei.value.data is not None
    assert ei.value.data.get("detail") == "data[0].embedding is missing"


def test_embed_client_rejects_non_numeric_embedding_values():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/embeddings"
        return httpx.Response(200, json={"data": [{"embedding": [0.1, "bad", 0.3]}]})

    client = EmbedClient("127.0.0.1", 0)
    client._client = _mock_client(handler)  # type: ignore[attr-defined]
    with pytest.raises(RpcError) as ei:
        client.embed(["가"])
    assert ei.value.code == ERR_UPSTREAM_BAD_RESPONSE
    assert ei.value.data is not None
    assert ei.value.data.get("detail") == "data[0].embedding[1] is not a finite number"


def test_embed_client_rejects_non_finite_embedding_values():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/embeddings"
        return httpx.Response(200, json={"data": [{"embedding": [0.1, "NaN", 0.3]}]})

    client = EmbedClient("127.0.0.1", 0)
    client._client = _mock_client(handler)  # type: ignore[attr-defined]
    with pytest.raises(RpcError) as ei:
        client.embed(["가"])
    assert ei.value.code == ERR_UPSTREAM_BAD_RESPONSE
    assert ei.value.data is not None
    assert ei.value.data.get("detail") == "data[0].embedding[1] is not a finite number"


def test_embed_empty_input_returns_empty():
    client = EmbedClient("127.0.0.1", 0)
    assert client.embed([]) == []


def test_rerank_client_normalizes_scores():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/rerank"
        return httpx.Response(
            200,
            json={
                "results": [
                    {"index": 2, "relevance_score": 0.9},
                    {"index": 0, "relevance_score": 0.7},
                ]
            },
        )

    client = RerankClient("127.0.0.1", 0)
    client._client = _mock_client(handler)  # type: ignore[attr-defined]
    results = client.rerank("질의", ["a", "b", "c"], top_k=2)
    assert results == [
        {"index": 2, "score": 0.9},
        {"index": 0, "score": 0.7},
    ]


def test_rerank_client_malformed_json_raises_bad_response():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/rerank"
        return httpx.Response(200, json={"results": [{"index": "x", "relevance_score": "bad"}]})

    client = RerankClient("127.0.0.1", 0)
    client._client = _mock_client(handler)  # type: ignore[attr-defined]
    with pytest.raises(RpcError) as ei:
        client.rerank("질의", ["a"])
    assert ei.value.code == ERR_UPSTREAM_BAD_RESPONSE
    assert ei.value.data is not None
    assert ei.value.data.get("detail") == "results[0] is missing numeric index/relevance_score"


def test_llm_http_5xx_raises_upstream_unavailable():
    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="oops")

    client = LlmClient("127.0.0.1", 0)
    client._client = _mock_client(handler)  # type: ignore[attr-defined]
    with pytest.raises(RpcError) as ei:
        client.chat("s", "u")
    assert ei.value.code == ERR_UPSTREAM_UNAVAILABLE


def test_llm_retries_transient_http_5xx_then_succeeds(monkeypatch: pytest.MonkeyPatch):
    attempts = {"count": 0}
    monkeypatch.setattr("eoditdeora.runtime.clients.time.sleep", lambda _sec: None)

    def handler(_req: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        if attempts["count"] < 3:
            return httpx.Response(502, text="bad gateway")
        return httpx.Response(
            200,
            json={"choices": [{"message": {"role": "assistant", "content": "복구됨"}}]},
        )

    client = LlmClient("127.0.0.1", 0)
    client._client = _mock_client(handler)  # type: ignore[attr-defined]
    assert client.chat("s", "u") == "복구됨"
    assert attempts["count"] == 3


def test_llm_401_raises_upstream_auth():
    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"message": "Invalid API Key"}})

    client = LlmClient("127.0.0.1", 0)
    client._client = _mock_client(handler)  # type: ignore[attr-defined]
    with pytest.raises(RpcError) as ei:
        client.chat("s", "u")
    assert ei.value.code == ERR_UPSTREAM_AUTH
    # Error data carries the URL and role so the UI can route the
    # user directly to the relevant settings row.
    assert ei.value.data is not None
    assert ei.value.data.get("role") == "llm"
    assert ei.value.data.get("detail") == "Invalid API Key"


def test_embed_401_raises_upstream_auth():
    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"error": "forbidden"})

    client = EmbedClient("127.0.0.1", 0)
    client._client = _mock_client(handler)  # type: ignore[attr-defined]
    with pytest.raises(RpcError) as ei:
        client.embed(["x"])
    assert ei.value.code == ERR_UPSTREAM_AUTH


def test_rerank_404_raises_upstream_not_found():
    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="no such route")

    client = RerankClient("127.0.0.1", 0)
    client._client = _mock_client(handler)  # type: ignore[attr-defined]
    with pytest.raises(RpcError) as ei:
        client.rerank("q", ["a"])
    assert ei.value.code == ERR_UPSTREAM_NOT_FOUND


def test_llm_connect_error_raises_upstream_unavailable():
    def handler(_req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    client = LlmClient("127.0.0.1", 0)
    client._client = _mock_client(handler)  # type: ignore[attr-defined]
    with pytest.raises(RpcError) as ei:
        client.chat("s", "u")
    assert ei.value.code == ERR_UPSTREAM_UNAVAILABLE


def test_embed_retries_transport_error_then_succeeds(monkeypatch: pytest.MonkeyPatch):
    attempts = {"count": 0}
    monkeypatch.setattr("eoditdeora.runtime.clients.time.sleep", lambda _sec: None)

    def handler(_req: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise httpx.ConnectError("connection refused")
        return httpx.Response(200, json={"data": [{"embedding": [0.1, 0.2]}]})

    client = EmbedClient("127.0.0.1", 0)
    client._client = _mock_client(handler)  # type: ignore[attr-defined]
    assert client.embed(["x"]) == [[0.1, 0.2]]
    assert attempts["count"] == 2


def test_llm_non_json_body_raises_bad_response():
    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            text="<html><title>Sign in</title><body>login required</body></html>",
            headers={"content-type": "text/html; charset=utf-8"},
        )

    client = LlmClient("127.0.0.1", 0)
    client._client = _mock_client(handler)  # type: ignore[attr-defined]
    with pytest.raises(RpcError) as ei:
        client.chat("s", "u")
    assert ei.value.code == ERR_UPSTREAM_BAD_RESPONSE
    assert ei.value.data is not None
    assert ei.value.data.get("detail") == (
        "content-type=text/html; charset=utf-8 | "
        "body=<html><title>Sign in</title><body>login required</body></html>"
    )


def test_llm_429_raises_rate_limit_after_retries(monkeypatch: pytest.MonkeyPatch):
    attempts = {"count": 0}
    monkeypatch.setattr("eoditdeora.runtime.clients.time.sleep", lambda _sec: None)

    def handler(_req: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        return httpx.Response(429, json={"error": "rate limited"})

    client = LlmClient("127.0.0.1", 0)
    client._client = _mock_client(handler)  # type: ignore[attr-defined]
    with pytest.raises(RpcError) as ei:
        client.chat("s", "u")
    assert ei.value.code == ERR_UPSTREAM_RATE_LIMIT
    assert attempts["count"] == 3
    assert ei.value.data is not None
    assert ei.value.data.get("retry_after_sec") == 0.2


def test_llm_429_honors_retry_after_header(monkeypatch: pytest.MonkeyPatch):
    attempts = {"count": 0}
    slept: list[float] = []
    monkeypatch.setattr("eoditdeora.runtime.clients.time.sleep", slept.append)

    def handler(_req: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        return httpx.Response(
            429,
            json={"error": "rate limited"},
            headers={"retry-after": "0.75"},
        )

    client = LlmClient("127.0.0.1", 0)
    client._client = _mock_client(handler)  # type: ignore[attr-defined]
    with pytest.raises(RpcError) as ei:
        client.chat("s", "u")
    assert ei.value.code == ERR_UPSTREAM_RATE_LIMIT
    assert attempts["count"] == 3
    assert slept == [0.75, 0.75]
    assert ei.value.data is not None
    assert ei.value.data.get("retry_after_sec") == 0.75


def test_llm_503_invalid_retry_after_falls_back_to_exponential_delay(
    monkeypatch: pytest.MonkeyPatch,
):
    attempts = {"count": 0}
    slept: list[float] = []
    monkeypatch.setattr("eoditdeora.runtime.clients.time.sleep", slept.append)

    def handler(_req: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        return httpx.Response(
            503,
            text="upstream overloaded",
            headers={"retry-after": "not-a-number"},
        )

    client = LlmClient("127.0.0.1", 0)
    client._client = _mock_client(handler)  # type: ignore[attr-defined]
    with pytest.raises(RpcError) as ei:
        client.chat("s", "u")
    assert ei.value.code == ERR_UPSTREAM_UNAVAILABLE
    assert attempts["count"] == 3
    assert slept == [0.2, 0.4]


def test_llm_400_generic_4xx_raises_bad_request():
    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": {"message": "model is required"}})

    client = LlmClient("127.0.0.1", 0)
    client._client = _mock_client(handler)  # type: ignore[attr-defined]
    with pytest.raises(RpcError) as ei:
        client.chat("s", "u")
    assert ei.value.code == ERR_UPSTREAM_BAD_REQUEST
    assert ei.value.data is not None
    assert ei.value.data.get("detail") == "model is required"
    assert "모델 ID" in ei.value.message


def test_llm_422_context_limit_raises_bad_request():
    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            422,
            json={"error": {"message": "maximum context length exceeded"}},
        )

    client = LlmClient("127.0.0.1", 0)
    client._client = _mock_client(handler)  # type: ignore[attr-defined]
    with pytest.raises(RpcError) as ei:
        client.chat("s", "u")
    assert ei.value.code == ERR_UPSTREAM_BAD_REQUEST
    assert "요청 길이" in ei.value.message


def test_llm_5xx_plain_text_detail_is_preserved_after_retries(
    monkeypatch: pytest.MonkeyPatch,
):
    attempts = {"count": 0}
    monkeypatch.setattr("eoditdeora.runtime.clients.time.sleep", lambda _sec: None)

    def handler(_req: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        return httpx.Response(503, text="upstream overloaded")

    client = LlmClient("127.0.0.1", 0)
    client._client = _mock_client(handler)  # type: ignore[attr-defined]
    with pytest.raises(RpcError) as ei:
        client.chat("s", "u")
    assert ei.value.code == ERR_UPSTREAM_UNAVAILABLE
    assert attempts["count"] == 3
    assert ei.value.data is not None
    assert ei.value.data.get("detail") == "upstream overloaded"


def test_llm_does_not_retry_non_retryable_404():
    attempts = {"count": 0}

    def handler(_req: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        return httpx.Response(404, text="no such route")

    client = LlmClient("127.0.0.1", 0)
    client._client = _mock_client(handler)  # type: ignore[attr-defined]
    with pytest.raises(RpcError) as ei:
        client.chat("s", "u")
    assert ei.value.code == ERR_UPSTREAM_NOT_FOUND
    assert attempts["count"] == 1


def test_llm_content_wins_over_reasoning_content():
    # Priority regression: when both are present, the real answer in
    # `content` must be returned, not the scratch pad in
    # `reasoning_content`.
    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "final answer",
                            "reasoning_content": "scratch pad",
                        }
                    }
                ]
            },
        )

    client = LlmClient("127.0.0.1", 0)
    client._client = _mock_client(handler)  # type: ignore[attr-defined]
    assert client.chat("s", "u") == "final answer"


def test_llm_reasoning_fallback_when_content_empty():
    # Reasoning models (gpt-oss etc.) sometimes return "" for content
    # when the token budget caps out before the final answer is emitted
    # but include the chain in `reasoning`. Fall back to that so the
    # retriever doesn't silently get an empty string.
    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "",
                            "reasoning": "the user asked to say hi",
                        },
                        "finish_reason": "length",
                    }
                ]
            },
        )

    client = LlmClient("127.0.0.1", 0)
    client._client = _mock_client(handler)  # type: ignore[attr-defined]
    assert client.chat("s", "u") == "the user asked to say hi"


def test_llm_reasoning_content_fallback_qwen_style():
    # Qwen reasoning models via llama-server use `reasoning_content`
    # rather than `reasoning`. Both fields need to fall through when
    # content is empty.
    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "",
                            "reasoning_content": "chain of thought body",
                        },
                        "finish_reason": "length",
                    }
                ]
            },
        )

    client = LlmClient("127.0.0.1", 0)
    client._client = _mock_client(handler)  # type: ignore[attr-defined]
    assert client.chat("s", "u") == "chain of thought body"


def test_llm_chat_joins_text_parts_from_content_array():
    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": [
                                {"type": "output_text", "text": "첫 문장"},
                                {"type": "text", "text": " 둘째 문장"},
                            ],
                        }
                    }
                ]
            },
        )

    client = LlmClient("127.0.0.1", 0)
    client._client = _mock_client(handler)  # type: ignore[attr-defined]
    assert client.chat("s", "u") == "첫 문장 둘째 문장"


def test_llm_chat_missing_message_raises_bad_response():
    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop"}]})

    client = LlmClient("127.0.0.1", 0)
    client._client = _mock_client(handler)  # type: ignore[attr-defined]
    with pytest.raises(RpcError) as ei:
        client.chat("s", "u")
    assert ei.value.code == ERR_UPSTREAM_BAD_RESPONSE
    assert ei.value.data is not None
    assert ei.value.data.get("detail") == "choices[0].message is missing"


def test_llm_chat_empty_message_text_raises_bad_response():
    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": [],
                            "reasoning": "",
                            "reasoning_content": None,
                        }
                    }
                ]
            },
        )

    client = LlmClient("127.0.0.1", 0)
    client._client = _mock_client(handler)  # type: ignore[attr-defined]
    with pytest.raises(RpcError) as ei:
        client.chat("s", "u")
    assert ei.value.code == ERR_UPSTREAM_BAD_RESPONSE
    assert ei.value.data is not None
    assert ei.value.data.get("detail") == "choices[0].message has no usable content/reasoning text"
