"""High-level retriever RPC service."""

from __future__ import annotations

from typing import Any

import pytest

from eoditdeora.retriever import service as service_mod


@pytest.mark.asyncio
async def test_search_mode_returns_results(monkeypatch: pytest.MonkeyPatch):
    calls: dict[str, Any] = {}

    def fake_hybrid(query: str, top_k: int = 10):  # type: ignore[no-untyped-def]
        calls["query"] = query
        calls["top_k"] = top_k
        return [{"chunk_id": "c1", "doc_id": "d1", "snippet": "내용"}]

    monkeypatch.setattr(service_mod, "hybrid_search", fake_hybrid)
    result = await service_mod.search("질의", top_k=5)
    assert result["results"] == [{"chunk_id": "c1", "doc_id": "d1", "snippet": "내용"}]
    assert "answer" not in result
    assert calls == {"query": "질의", "top_k": 5}


@pytest.mark.asyncio
async def test_ask_mode_includes_answer(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        service_mod,
        "hybrid_search",
        lambda q, top_k=10: [{"chunk_id": "c1", "doc_id": "d1", "snippet": "s", "source_path": "/x"}],
    )
    monkeypatch.setattr(
        service_mod,
        "answer_strict",
        lambda q, hits: {"answered": True, "answer": "예 [§1]", "citations": []},
    )
    result = await service_mod.search("질의", top_k=3, mode="ask")
    assert result["answer"]["answered"] is True
    assert result["answer"]["answer"] == "예 [§1]"
