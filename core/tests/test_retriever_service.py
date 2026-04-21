"""High-level retriever RPC service."""

from __future__ import annotations

from typing import Any

import pytest

from eoditdeora.api.rpc_server import ERR_UPSTREAM_UNAVAILABLE, RpcError
from eoditdeora.retriever import service as service_mod


@pytest.mark.asyncio
async def test_search_mode_returns_results(monkeypatch: pytest.MonkeyPatch):
    """Default mode ('search') uses the pure-lexical path — no hybrid."""
    calls: dict[str, Any] = {}

    def fake_lexical(query: str, *, top_k: int = 20):  # type: ignore[no-untyped-def]
        calls["query"] = query
        calls["top_k"] = top_k
        return [{"chunk_id": "c1", "doc_id": "d1", "snippet": "내용"}]

    def forbid_hybrid(*_a: Any, **_k: Any) -> list[dict[str, Any]]:
        raise AssertionError("mode='search' must not call hybrid_search")

    monkeypatch.setattr(service_mod, "lexical_search", fake_lexical)
    monkeypatch.setattr(service_mod, "hybrid_search", forbid_hybrid)

    result = await service_mod.search("질의", top_k=5)
    assert result["results"] == [{"chunk_id": "c1", "doc_id": "d1", "snippet": "내용"}]
    assert "answer" not in result
    assert calls == {"query": "질의", "top_k": 5}


@pytest.mark.asyncio
async def test_search_records_query(monkeypatch: pytest.MonkeyPatch):
    calls: list[str] = []

    class FakeHistoryStore:
        def record_query(self, query: str) -> None:
            calls.append(query)

        def close(self) -> None:
            return None

    monkeypatch.setattr(service_mod, "HistoryStore", FakeHistoryStore)
    monkeypatch.setattr(service_mod, "lexical_search", lambda *_a, **_k: [])

    await service_mod.search("최근 검색")

    assert calls == ["최근 검색"]


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


@pytest.mark.asyncio
async def test_search_with_non_positive_top_k_short_circuits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbid_lexical(*_a: Any, **_k: Any) -> list[dict[str, Any]]:
        raise AssertionError("non-positive top_k must not call lexical_search")

    def forbid_hybrid(*_a: Any, **_k: Any) -> list[dict[str, Any]]:
        raise AssertionError("non-positive top_k must not call hybrid_search")

    monkeypatch.setattr(service_mod, "lexical_search", forbid_lexical)
    monkeypatch.setattr(service_mod, "hybrid_search", forbid_hybrid)

    result = await service_mod.search("질의", top_k=0)
    assert result == {"query": "질의", "results": []}


@pytest.mark.asyncio
async def test_ask_mode_preserves_structured_rpc_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        service_mod,
        "hybrid_search",
        lambda q, top_k=10: [{"chunk_id": "c1", "doc_id": "d1", "snippet": "s", "source_path": "/x"}],
    )

    def fail_answer(_q: str, _hits: list[dict[str, Any]]) -> dict[str, Any]:
        raise RpcError(
            ERR_UPSTREAM_UNAVAILABLE,
            "추론 서버에 연결할 수 없습니다",
            {"role": "llm", "detail": "connection refused"},
        )

    monkeypatch.setattr(service_mod, "answer_strict", fail_answer)

    with pytest.raises(RpcError) as ei:
        await service_mod.search("질의", top_k=3, mode="ask")

    assert ei.value.code == ERR_UPSTREAM_UNAVAILABLE
