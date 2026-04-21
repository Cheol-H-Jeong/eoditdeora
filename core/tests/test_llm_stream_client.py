from __future__ import annotations

from collections.abc import Iterator

import httpx
import pytest

from eoditdeora.api.rpc_server import (
    ERR_UPSTREAM_BAD_REQUEST,
    ERR_UPSTREAM_BAD_RESPONSE,
    ERR_UPSTREAM_RATE_LIMIT,
    ERR_UPSTREAM_UNAVAILABLE,
    RpcError,
)
from eoditdeora.runtime.clients import LlmClient


class _MockStreamResponse:
    def __init__(
        self,
        lines: list[str],
        status_code: int = 200,
        *,
        json_data: object | None = None,
        text: str = "",
    ) -> None:
        self._lines = lines
        self.status_code = status_code
        self._json_data = json_data
        self.text = text

    def __enter__(self) -> _MockStreamResponse:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def iter_lines(self) -> Iterator[str]:
        yield from self._lines

    def json(self) -> object:
        if self._json_data is None:
            raise ValueError("no json body")
        return self._json_data


def test_chat_stream_yields_content_chunks_in_order(monkeypatch: pytest.MonkeyPatch):
    seen: dict[str, object] = {}

    def fake_stream(method: str, url: str, **kwargs):
        seen["method"] = method
        seen["url"] = url
        seen["json"] = kwargs["json"]
        return _MockStreamResponse(
            [
                'data: {"choices":[{"delta":{"content":"안녕"}}]}',
                'data: {"choices":[{"delta":{"content":" 하세요"}}]}',
                "data: [DONE]",
            ]
        )

    monkeypatch.setattr(httpx, "stream", fake_stream)
    client = LlmClient("127.0.0.1", 0)

    assert list(client.chat_stream("sys", "usr", max_tokens=64)) == ["안녕", " 하세요"]
    assert seen["method"] == "POST"
    assert seen["url"] == "http://127.0.0.1:0/v1/chat/completions"
    assert isinstance(seen["json"], dict)
    assert seen["json"]["stream"] is True


def test_chat_stream_uses_reasoning_fallback_fields(monkeypatch: pytest.MonkeyPatch):
    def fake_stream(_method: str, _url: str, **_kwargs):
        return _MockStreamResponse(
            [
                'data: {"choices":[{"delta":{"reasoning_content":"생각 "}}]}',
                'data: {"choices":[{"delta":{"reasoning":"정리"}}]}',
                "data: [DONE]",
            ]
        )

    monkeypatch.setattr(httpx, "stream", fake_stream)
    client = LlmClient("127.0.0.1", 0)

    assert list(client.chat_stream("sys", "usr")) == ["생각 ", "정리"]


def test_chat_stream_joins_text_parts_from_content_array(
    monkeypatch: pytest.MonkeyPatch,
):
    def fake_stream(_method: str, _url: str, **_kwargs):
        return _MockStreamResponse(
            [
                'data: {"choices":[{"delta":{"content":[{"type":"output_text","text":"첫 "},{"type":"text","text":"조각"}]}}]}',
                'data: {"choices":[{"delta":{"content":[{"type":"text","text":" 둘째 조각"}]}}]}',
                "data: [DONE]",
            ]
        )

    monkeypatch.setattr(httpx, "stream", fake_stream)
    client = LlmClient("127.0.0.1", 0)

    assert list(client.chat_stream("sys", "usr")) == ["첫 조각", " 둘째 조각"]


def test_chat_stream_stops_at_done(monkeypatch: pytest.MonkeyPatch):
    def fake_stream(_method: str, _url: str, **_kwargs):
        return _MockStreamResponse(
            [
                'data: {"choices":[{"delta":{"content":"first"}}]}',
                "data: [DONE]",
                'data: {"choices":[{"delta":{"content":"late"}}]}',
            ]
        )

    monkeypatch.setattr(httpx, "stream", fake_stream)
    client = LlmClient("127.0.0.1", 0)

    assert list(client.chat_stream("sys", "usr")) == ["first"]


def test_chat_stream_wraps_network_errors(monkeypatch: pytest.MonkeyPatch):
    def fake_stream(_method: str, _url: str, **_kwargs):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx, "stream", fake_stream)
    client = LlmClient("127.0.0.1", 0)

    with pytest.raises(RpcError) as ei:
        list(client.chat_stream("sys", "usr"))
    assert ei.value.code == ERR_UPSTREAM_UNAVAILABLE


def test_chat_stream_retries_transport_error_then_succeeds(monkeypatch: pytest.MonkeyPatch):
    attempts = {"count": 0}
    monkeypatch.setattr("eoditdeora.runtime.clients.time.sleep", lambda _sec: None)

    def fake_stream(_method: str, _url: str, **_kwargs):
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise httpx.ConnectError("connection refused")
        return _MockStreamResponse(
            [
                'data: {"choices":[{"delta":{"content":"복구"}}]}',
                "data: [DONE]",
            ]
        )

    monkeypatch.setattr(httpx, "stream", fake_stream)
    client = LlmClient("127.0.0.1", 0)

    assert list(client.chat_stream("sys", "usr")) == ["복구"]
    assert attempts["count"] == 2


def test_chat_stream_surfaces_rate_limit(monkeypatch: pytest.MonkeyPatch):
    def fake_stream(_method: str, _url: str, **_kwargs):
        return _MockStreamResponse(
            [],
            status_code=429,
            json_data={"error": {"message": "too many requests"}},
        )

    monkeypatch.setattr(httpx, "stream", fake_stream)
    client = LlmClient("127.0.0.1", 0)

    with pytest.raises(RpcError) as ei:
        list(client.chat_stream("sys", "usr"))
    assert ei.value.code == ERR_UPSTREAM_RATE_LIMIT
    assert ei.value.data is not None
    assert ei.value.data.get("detail") == "too many requests"


def test_chat_stream_surfaces_bad_request(monkeypatch: pytest.MonkeyPatch):
    def fake_stream(_method: str, _url: str, **_kwargs):
        return _MockStreamResponse(
            [],
            status_code=400,
            json_data={"error": {"message": "model is required"}},
        )

    monkeypatch.setattr(httpx, "stream", fake_stream)
    client = LlmClient("127.0.0.1", 0)

    with pytest.raises(RpcError) as ei:
        list(client.chat_stream("sys", "usr"))
    assert ei.value.code == ERR_UPSTREAM_BAD_REQUEST
    assert "모델 ID" in ei.value.message


def test_chat_stream_retries_transient_http_5xx_then_succeeds(
    monkeypatch: pytest.MonkeyPatch,
):
    attempts = {"count": 0}
    monkeypatch.setattr("eoditdeora.runtime.clients.time.sleep", lambda _sec: None)

    def fake_stream(_method: str, _url: str, **_kwargs):
        attempts["count"] += 1
        if attempts["count"] < 3:
            return _MockStreamResponse([], status_code=502)
        return _MockStreamResponse(
            [
                'data: {"choices":[{"delta":{"content":"정상화"}}]}',
                "data: [DONE]",
            ]
        )

    monkeypatch.setattr(httpx, "stream", fake_stream)
    client = LlmClient("127.0.0.1", 0)

    assert list(client.chat_stream("sys", "usr")) == ["정상화"]
    assert attempts["count"] == 3


def test_chat_stream_does_not_retry_after_partial_output(
    monkeypatch: pytest.MonkeyPatch,
):
    attempts = {"count": 0}
    monkeypatch.setattr("eoditdeora.runtime.clients.time.sleep", lambda _sec: None)

    class _BrokenMidStreamResponse(_MockStreamResponse):
        def iter_lines(self) -> Iterator[str]:
            yield 'data: {"choices":[{"delta":{"content":"첫 청크"}}]}'
            raise httpx.ReadError("socket closed")

    def fake_stream(_method: str, _url: str, **_kwargs):
        attempts["count"] += 1
        return _BrokenMidStreamResponse([])

    monkeypatch.setattr(httpx, "stream", fake_stream)
    client = LlmClient("127.0.0.1", 0)

    chunks: list[str] = []
    with pytest.raises(RpcError) as ei:
        for chunk in client.chat_stream("sys", "usr"):
            chunks.append(chunk)
    assert chunks == ["첫 청크"]
    assert ei.value.code == ERR_UPSTREAM_UNAVAILABLE
    assert attempts["count"] == 1


def test_chat_stream_bad_sse_chunk_preserves_payload_detail(
    monkeypatch: pytest.MonkeyPatch,
):
    def fake_stream(_method: str, _url: str, **_kwargs):
        return _MockStreamResponse(
            [
                "data: {not json",
                "data: [DONE]",
            ]
        )

    monkeypatch.setattr(httpx, "stream", fake_stream)
    client = LlmClient("127.0.0.1", 0)

    with pytest.raises(RpcError) as ei:
        list(client.chat_stream("sys", "usr"))
    assert ei.value.code == ERR_UPSTREAM_BAD_RESPONSE
    assert ei.value.data is not None
    assert ei.value.data.get("detail") == "sse_chunk={not json"
