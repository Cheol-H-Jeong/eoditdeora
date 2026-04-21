from __future__ import annotations

from typing import Any

import pytest

from eoditdeora.retriever import rag as rag_mod
from eoditdeora.retriever.rag import answer_strict_stream


class _FakeStreamingLlm:
    def __init__(self, chunks: list[str], *, error: Exception | None = None) -> None:
        self._chunks = chunks
        self._error = error
        self.calls: list[dict[str, Any]] = []
        self.closed = False

    def chat_stream(self, system: str, user: str, **kw: Any):  # noqa: ARG002
        self.calls.append({"system": system, "user": user, "kw": kw})
        if self._error is not None:
            raise self._error
        yield from self._chunks

    def close(self) -> None:
        self.closed = True


def _hits():
    return [
        {
            "chunk_id": "c1",
            "doc_id": "d1",
            "snippet": "사업 예산은 120,000,000원입니다",
            "source_path": "/tmp/a.pdf",
            "source_path_display": "/tmp/a.pdf",
        },
        {
            "chunk_id": "c2",
            "doc_id": "d1",
            "snippet": "집행 시기는 2025년 3분기",
            "source_path": "/tmp/a.pdf",
            "source_path_display": "/tmp/a.pdf",
        },
    ]


def test_answer_strict_stream_emits_chunk_then_done(monkeypatch: pytest.MonkeyPatch):
    llm = _FakeStreamingLlm(["예산은 ", "1.2억원입니다 [§1]."])
    monkeypatch.setattr(rag_mod, "get_llm_client", lambda: llm)

    events = list(answer_strict_stream("예산은?", _hits()))

    assert events == [
        {"type": "chunk", "text": "예산은 "},
        {"type": "chunk", "text": "1.2억원입니다 [§1]."},
        {
            "type": "done",
            "citations": [
                {
                    "index": 1,
                    "doc_id": "d1",
                    "chunk_id": "c1",
                    "source_path": "/tmp/a.pdf",
                    "source_path_display": "/tmp/a.pdf",
                },
                {
                    "index": 2,
                    "doc_id": "d1",
                    "chunk_id": "c2",
                    "source_path": "/tmp/a.pdf",
                    "source_path_display": "/tmp/a.pdf",
                },
            ],
        },
    ]
    assert llm.closed is True


def test_answer_strict_stream_emits_error_on_stream_failure(
    monkeypatch: pytest.MonkeyPatch,
):
    llm = _FakeStreamingLlm([], error=RuntimeError("boom"))
    monkeypatch.setattr(rag_mod, "get_llm_client", lambda: llm)

    events = list(answer_strict_stream("질문", _hits()))

    assert events == [{"type": "error", "error": "LLM 엔드포인트 호출에 실패했습니다: boom"}]
    assert llm.closed is True


def test_answer_strict_stream_empty_hits_returns_no_answer_chunk():
    events = list(answer_strict_stream("질문", []))

    assert events == [
        {"type": "chunk", "text": "근거 문서에 해당 정보가 없어 답변할 수 없습니다."},
        {"type": "done", "citations": []},
    ]
