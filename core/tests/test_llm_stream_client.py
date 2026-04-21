from __future__ import annotations

from collections.abc import Iterator

import httpx
import pytest

from eoditdeora.api.rpc_server import ERR_UPSTREAM_RATE_LIMIT, ERR_UPSTREAM_UNAVAILABLE, RpcError
from eoditdeora.runtime.clients import LlmClient


class _MockStreamResponse:
    def __init__(self, lines: list[str], status_code: int = 200) -> None:
        self._lines = lines
        self.status_code = status_code

    def __enter__(self) -> _MockStreamResponse:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def iter_lines(self) -> Iterator[str]:
        yield from self._lines


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


def test_chat_stream_surfaces_rate_limit(monkeypatch: pytest.MonkeyPatch):
    def fake_stream(_method: str, _url: str, **_kwargs):
        return _MockStreamResponse([], status_code=429)

    monkeypatch.setattr(httpx, "stream", fake_stream)
    client = LlmClient("127.0.0.1", 0)

    with pytest.raises(RpcError) as ei:
        list(client.chat_stream("sys", "usr"))
    assert ei.value.code == ERR_UPSTREAM_RATE_LIMIT
