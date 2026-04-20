"""Strict-provenance RAG answer generator."""

from __future__ import annotations

from typing import Any

import pytest

from eoditdeora.retriever import rag as rag_mod
from eoditdeora.retriever.rag import answer_strict


class _FakeSup:
    host = "127.0.0.1"

    def __init__(self, running: bool = True) -> None:
        self._running = running

    def is_running(self, _name: str) -> bool:
        return self._running

    def port(self, _name: str) -> int:
        return 0


class _FakeLlm:
    def __init__(self, response: str) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []

    def __init__wrapper(self, *a, **k):  # type: ignore[no-untyped-def]
        pass

    def chat(self, system: str, user: str, **kw: Any) -> str:  # noqa: ARG002
        self.calls.append({"system": system, "user": user, "kw": kw})
        return self.response

    def close(self) -> None:
        pass


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


def test_answer_strict_returns_citations(monkeypatch: pytest.MonkeyPatch):
    llm = _FakeLlm("예산은 1.2억원입니다 [§1].")
    monkeypatch.setattr(rag_mod, "RuntimeSupervisor", lambda: _FakeSup())
    monkeypatch.setattr(rag_mod, "LlmClient", lambda host, port: llm)

    result = answer_strict("예산은?", _hits())
    assert result["answered"] is True
    assert result["answer"] == "예산은 1.2억원입니다 [§1]."
    assert len(result["citations"]) == 2
    assert result["citations"][0]["index"] == 1
    assert result["citations"][0]["source_path_display"] == "/tmp/a.pdf"


def test_empty_evidence_returns_no_answer():
    result = answer_strict("질문", [])
    assert result["answered"] is False
    assert "근거 문서에 해당 정보가 없어" in result["answer"]
    assert result["citations"] == []


def test_llm_offline_returns_no_answer(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(rag_mod, "RuntimeSupervisor", lambda: _FakeSup(running=False))
    result = answer_strict("질문", _hits())
    assert result["answered"] is False
    assert result["citations"] == []


def test_no_evidence_sentinel_detected(monkeypatch: pytest.MonkeyPatch):
    llm = _FakeLlm("근거 문서에 해당 정보가 없어 답변할 수 없습니다.")
    monkeypatch.setattr(rag_mod, "RuntimeSupervisor", lambda: _FakeSup())
    monkeypatch.setattr(rag_mod, "LlmClient", lambda host, port: llm)
    result = answer_strict("알 수 없는 질문", _hits())
    assert result["answered"] is False


def test_system_prompt_enforces_strict_mode(monkeypatch: pytest.MonkeyPatch):
    llm = _FakeLlm("응답")
    monkeypatch.setattr(rag_mod, "RuntimeSupervisor", lambda: _FakeSup())
    monkeypatch.setattr(rag_mod, "LlmClient", lambda host, port: llm)
    answer_strict("질문", _hits())
    system = llm.calls[0]["system"]
    assert "근거" in system
    assert "각주" in system
    assert "추측" in system or "사전지식" in system
