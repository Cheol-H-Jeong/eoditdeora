"""Strict-provenance RAG answer generator."""

from __future__ import annotations

from typing import Any

import pytest

from eoditdeora.api.rpc_server import ERR_UPSTREAM_AUTH, RpcError
from eoditdeora.retriever import rag as rag_mod
from eoditdeora.retriever.rag import answer_strict


class _FakeLlm:
    def __init__(self, response: str) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []

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
    monkeypatch.setattr(rag_mod, "get_llm_client", lambda: llm)
    result = answer_strict("예산은?", _hits())
    assert result["answered"] is True
    assert result["answer"] == "예산은 1.2억원입니다 [§1]."
    assert len(result["citations"]) == 2
    assert result["citations"][0]["source_path_display"] == "/tmp/a.pdf"


def test_empty_evidence_returns_no_answer():
    result = answer_strict("질문", [])
    assert result["answered"] is False
    assert "근거 문서에 해당 정보가 없어" in result["answer"]


def test_no_endpoint_returns_no_answer(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(rag_mod, "get_llm_client", lambda: None)
    result = answer_strict("질문", _hits())
    assert result["answered"] is False
    assert "엔드포인트" in result["answer"]


def test_no_evidence_sentinel_detected(monkeypatch: pytest.MonkeyPatch):
    llm = _FakeLlm("근거 문서에 해당 정보가 없어 답변할 수 없습니다.")
    monkeypatch.setattr(rag_mod, "get_llm_client", lambda: llm)
    result = answer_strict("알 수 없는 질문", _hits())
    assert result["answered"] is False


def test_system_prompt_enforces_strict_mode(monkeypatch: pytest.MonkeyPatch):
    llm = _FakeLlm("응답")
    monkeypatch.setattr(rag_mod, "get_llm_client", lambda: llm)
    answer_strict("질문", _hits())
    system = llm.calls[0]["system"]
    assert "근거" in system
    assert "각주" in system
    assert "추측" in system or "사전지식" in system


def test_upstream_rpc_error_is_preserved(monkeypatch: pytest.MonkeyPatch):
    class FailingLlm:
        def __init__(self) -> None:
            self.closed = False

        def chat(self, system: str, user: str, **kw: Any) -> str:  # noqa: ARG002
            raise RpcError(
                ERR_UPSTREAM_AUTH,
                "API 키가 필요하거나 유효하지 않습니다",
                {"role": "llm", "status": 401},
            )

        def close(self) -> None:
            self.closed = True

    llm = FailingLlm()
    monkeypatch.setattr(rag_mod, "get_llm_client", lambda: llm)

    with pytest.raises(RpcError) as ei:
        answer_strict("질문", _hits())

    assert ei.value.code == ERR_UPSTREAM_AUTH
    assert llm.closed is True
