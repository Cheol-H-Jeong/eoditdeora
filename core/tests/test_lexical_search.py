"""Pure-lexical body search — the "내용" tab contract.

These tests pin the rule: ``service.search(mode="search")`` must NOT
touch the embed or rerank clients. If Tantivy is populated, results
come back immediately; if it isn't, we get an empty list and a
``no_results`` warning — but we never call out to an AI server on this
path.
"""

from __future__ import annotations

from typing import Any

import pytest

from eoditdeora.retriever import lexical as lexical_mod
from eoditdeora.retriever import service as service_mod


@pytest.mark.asyncio
async def test_search_mode_never_touches_embed_or_rerank(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """mode='search' must stay on the BM25 path — no embed, no rerank."""
    called: list[str] = []

    def boom_embed() -> None:  # pragma: no cover - should never execute
        called.append("embed")
        raise AssertionError("lexical path must not call embed")

    def boom_rerank() -> None:  # pragma: no cover
        called.append("rerank")
        raise AssertionError("lexical path must not call rerank")

    monkeypatch.setattr(
        "eoditdeora.runtime.clients.get_embed_client", boom_embed
    )
    monkeypatch.setattr(
        "eoditdeora.runtime.clients.get_rerank_client", boom_rerank
    )

    def stub_lexical(query: str, *, top_k: int = 20) -> list[dict[str, Any]]:
        return [
            {
                "chunk_id": "c1",
                "doc_id": "d1",
                "snippet": "예산 품의서 초안",
                "score": 9.5,
                "fusion_score": None,
                "source_path": "/tmp/a.pdf",
                "source_path_display": "/tmp/a.pdf",
                "format": "pdf",
                "title": "예산 품의서",
                "classification": None,
            }
        ]

    monkeypatch.setattr(service_mod, "lexical_search", stub_lexical)

    out = await service_mod.search("예산", top_k=5, mode="search")
    assert called == [], "embed/rerank must not be invoked for lexical search"
    assert out["results"][0]["snippet"] == "예산 품의서 초안"
    assert "warning" not in out


@pytest.mark.asyncio
async def test_search_mode_empty_returns_no_results_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        service_mod, "lexical_search", lambda q, *, top_k=20: []
    )
    out = await service_mod.search("nothing matches", mode="search")
    assert out["results"] == []
    assert out["warning"] == "no_results"


@pytest.mark.asyncio
async def test_search_mode_crash_returns_structured_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A blow-up in the Tantivy layer must NOT kill the sidecar —
    the service wrapper translates it into a ``search_backend_failed``
    warning so the UI stays alive."""
    def boom(query: str, *, top_k: int = 20) -> list[dict[str, Any]]:
        raise RuntimeError("tantivy died")

    monkeypatch.setattr(service_mod, "lexical_search", boom)
    out = await service_mod.search("x", mode="search")
    assert out["results"] == []
    assert out["warning"] == "search_backend_failed"
    assert "tantivy died" in out["detail"]


@pytest.mark.asyncio
async def test_ask_mode_still_uses_hybrid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression guard: flipping mode to 'ask' must still go through
    the full hybrid path, not the lexical shortcut."""
    hybrid_called = {"n": 0}

    def hybrid_stub(query: str, *, top_k: int = 10) -> list[dict[str, Any]]:
        hybrid_called["n"] += 1
        return [
            {
                "chunk_id": "c1",
                "doc_id": "d1",
                "snippet": "hit",
                "score": 1.0,
                "source_path_display": "/x",
            }
        ]

    def lexical_stub(query: str, *, top_k: int = 20) -> list[dict[str, Any]]:
        raise AssertionError("ask mode must not take the lexical path")

    def answer_stub(query: str, hits: list[dict[str, Any]]) -> dict[str, Any]:
        return {"answered": True, "answer": "ok", "citations": []}

    monkeypatch.setattr(service_mod, "hybrid_search", hybrid_stub)
    monkeypatch.setattr(service_mod, "lexical_search", lexical_stub)
    monkeypatch.setattr(service_mod, "answer_strict", answer_stub)

    out = await service_mod.search("q", mode="ask")
    assert hybrid_called["n"] == 1
    assert out["answer"]["answered"] is True


def test_lexical_search_degrades_when_fts_open_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the Tantivy store fails to open we must return [] — not raise."""
    class Boom:
        def __init__(self, *a: object, **kw: object) -> None:
            raise RuntimeError("no index dir")

    monkeypatch.setattr(lexical_mod, "FtsStore", Boom)
    assert lexical_mod.lexical_search("x") == []


@pytest.mark.asyncio
async def test_search_mode_surfaces_real_fts_search_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class BrokenFts:
        def search(self, *_a: object, **_k: object) -> list[dict[str, Any]]:
            raise RuntimeError("tantivy index corrupt")

    monkeypatch.setattr(lexical_mod, "FtsStore", BrokenFts)

    out = await service_mod.search("예산", mode="search")
    assert out["results"] == []
    assert out["warning"] == "search_backend_failed"
    assert "tantivy index corrupt" in out["detail"]


def test_lexical_search_empty_query_short_circuits() -> None:
    assert lexical_mod.lexical_search("") == []
    assert lexical_mod.lexical_search("   ") == []
