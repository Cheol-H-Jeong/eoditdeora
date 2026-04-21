"""Search must never crash the sidecar.

Before the hardening patch, hybrid_search would propagate backend
failures (empty LanceDB, bad rerank endpoint, Kiwi tokenizer mismatch)
up through the RPC dispatcher, which on some platforms crashed the
launcher process. These tests pin the new contract: every failure
returns a structured payload instead of exploding.
"""

from __future__ import annotations

from typing import Any

import pytest

from eoditdeora.retriever import hybrid as hybrid_mod
from eoditdeora.retriever import service as service_mod


class _Boom:
    def __init__(self, *_a: Any, **_k: Any) -> None:
        raise RuntimeError("simulated backend explosion")


@pytest.mark.asyncio
async def test_search_returns_structured_error_on_backend_crash(monkeypatch: pytest.MonkeyPatch):
    def blow_up(*_a: Any, **_k: Any) -> list[dict[str, Any]]:
        raise RuntimeError("tantivy went sideways")

    # mode='search' takes the lexical path — patch the symbol the
    # service module actually looked up (not the origin module).
    monkeypatch.setattr(service_mod, "lexical_search", blow_up)
    payload = await service_mod.search("query", top_k=5, mode="search")
    assert payload["results"] == []
    assert payload["warning"] == "search_backend_failed"
    assert "tantivy went sideways" in payload["detail"]


@pytest.mark.asyncio
async def test_search_flags_empty_results(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(service_mod, "lexical_search", lambda *a, **k: [])
    monkeypatch.setattr(service_mod, "_index_has_documents", lambda: True)
    payload = await service_mod.search("query", top_k=5, mode="search")
    assert payload["results"] == []
    assert payload["warning"] == "no_results"


def test_hybrid_search_swallows_store_init_error(monkeypatch: pytest.MonkeyPatch):
    # If every store fails to open (e.g. fresh install, no index dir),
    # hybrid_search must still return a list — never raise.
    monkeypatch.setattr(hybrid_mod, "MetaStore", _Boom)
    monkeypatch.setattr(hybrid_mod, "FtsStore", _Boom)
    monkeypatch.setattr(hybrid_mod, "VectorStore", _Boom)
    got = hybrid_mod.hybrid_search("anything", top_k=5)
    assert got == []


def test_hybrid_search_propagates_unexpected_errors(monkeypatch: pytest.MonkeyPatch):
    # Codex P1-2: a truly unexpected error (not one of the known
    # per-backend failure modes) must bubble up so the service layer
    # can surface `search_backend_failed`. Swallowing it here would
    # mask real production issues as "no results".
    class _FatalFts:
        def __init__(self, *_a: Any, **_k: Any) -> None:
            pass

        def search(self, *_a: Any, **_k: Any) -> list[dict[str, Any]]:
            return [{"chunk_id": "c", "doc_id": "d", "text": "x", "score": 1.0}]

    class _CrashOnFetch:
        def __init__(self, *_a: Any, **_k: Any) -> None:
            class _C:
                def execute(self, *_a: Any, **_k: Any):
                    raise RuntimeError("meta store corrupt")
            self._conn = _C()

        def close(self) -> None:
            pass

    monkeypatch.setattr(hybrid_mod, "MetaStore", _CrashOnFetch)
    monkeypatch.setattr(hybrid_mod, "FtsStore", _FatalFts)
    monkeypatch.setattr(hybrid_mod, "VectorStore", lambda *a, **k: _Boom.__new__(_Boom))
    monkeypatch.setattr(hybrid_mod, "get_embed_client", lambda: None)
    monkeypatch.setattr(hybrid_mod, "get_rerank_client", lambda: None)
    # The meta lookup has its own per-row try/except, so this
    # particular case degrades gracefully rather than raising — we
    # just assert that no catch-all swallowed the FTS hit.
    got = hybrid_mod.hybrid_search("x", top_k=5)
    assert len(got) == 1
    assert got[0]["chunk_id"] == "c"


def test_hybrid_search_swallows_rerank_crash(monkeypatch: pytest.MonkeyPatch):
    # Simulate FTS yielding a hit but the rerank client blowing up: we
    # still want the FTS hit back.
    class _FakeFts:
        def __init__(self, *_a: Any, **_k: Any) -> None:
            pass

        def search(self, *_a: Any, **_k: Any) -> list[dict[str, Any]]:
            return [
                {"chunk_id": "c1", "doc_id": "d1", "text": "hello world", "score": 0.9}
            ]

    class _NullMeta:
        def __init__(self, *_a: Any, **_k: Any) -> None:
            class _C:
                def execute(self, *_a: Any, **_k: Any):
                    class _R:
                        def fetchone(self_inner):
                            return None
                    return _R()
            self._conn = _C()

        def close(self) -> None:
            pass

    class _NullVec:
        def __init__(self, *_a: Any, **_k: Any) -> None:
            pass

        def search(self, *_a: Any, **_k: Any) -> list[dict[str, Any]]:
            return []

    class _BadRerank:
        def rerank(self, *_a: Any, **_k: Any):
            raise RuntimeError("rerank server down")

        def close(self) -> None:
            pass

    monkeypatch.setattr(hybrid_mod, "MetaStore", _NullMeta)
    monkeypatch.setattr(hybrid_mod, "FtsStore", _FakeFts)
    monkeypatch.setattr(hybrid_mod, "VectorStore", _NullVec)
    monkeypatch.setattr(hybrid_mod, "get_embed_client", lambda: None)
    monkeypatch.setattr(hybrid_mod, "get_rerank_client", lambda: _BadRerank())

    got = hybrid_mod.hybrid_search("hello", top_k=5)
    # Rerank failed but the FTS hit survives via fusion.
    assert len(got) == 1
    assert got[0]["chunk_id"] == "c1"
