"""LLM runtime client tests using an in-process HTTP mock.

llama-server exposes OpenAI-compatible endpoints. We simulate them with
httpx.MockTransport so the client logic (request shape + response
parsing) is exercised without needing a real server.
"""

from __future__ import annotations

import json as _json

import httpx
import pytest

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


def test_llm_http_error_surfaces():
    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="oops")

    client = LlmClient("127.0.0.1", 0)
    client._client = _mock_client(handler)  # type: ignore[attr-defined]
    with pytest.raises(httpx.HTTPStatusError):
        client.chat("s", "u")
