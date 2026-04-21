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
    ERR_UPSTREAM_NOT_FOUND,
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
        return httpx.Response(401, json={"error": "Invalid API Key"})

    client = LlmClient("127.0.0.1", 0)
    client._client = _mock_client(handler)  # type: ignore[attr-defined]
    with pytest.raises(RpcError) as ei:
        client.chat("s", "u")
    assert ei.value.code == ERR_UPSTREAM_AUTH
    # Error data carries the URL and role so the UI can route the
    # user directly to the relevant settings row.
    assert ei.value.data is not None
    assert ei.value.data.get("role") == "llm"


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
        return httpx.Response(200, text="<html>login</html>")

    client = LlmClient("127.0.0.1", 0)
    client._client = _mock_client(handler)  # type: ignore[attr-defined]
    with pytest.raises(RpcError) as ei:
        client.chat("s", "u")
    from eoditdeora.api.rpc_server import ERR_UPSTREAM_BAD_RESPONSE
    assert ei.value.code == ERR_UPSTREAM_BAD_RESPONSE


def test_llm_400_generic_4xx_raises_unavailable():
    # 400/422/429 are not auth or route errors but the user still can't
    # get an answer. They fold into the generic unavailable bucket so
    # the UI gets a sensible "추론 서버 오류" message.
    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": "rate limited"})

    client = LlmClient("127.0.0.1", 0)
    client._client = _mock_client(handler)  # type: ignore[attr-defined]
    with pytest.raises(RpcError) as ei:
        client.chat("s", "u")
    assert ei.value.code == ERR_UPSTREAM_UNAVAILABLE


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
