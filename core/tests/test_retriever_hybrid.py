"""Hybrid retriever end-to-end.

Embed + rerank clients are injected via monkeypatching the factory
helpers in `eoditdeora.runtime.clients`. The unconfigured case uses
the default settings (empty base_url → factories return None).
"""

from __future__ import annotations

import time
from typing import Any

import pytest

from eoditdeora.retriever import hybrid as hybrid_mod
from eoditdeora.retriever.hybrid import hybrid_search
from eoditdeora.storage.fts import FtsStore
from eoditdeora.storage.meta import MetaStore
from eoditdeora.storage.vectors import EMBED_DIM, VectorStore


def _seed(meta: MetaStore, doc_id: str, path: str) -> None:
    meta.upsert_document(
        {
            "doc_id": doc_id,
            "root": "/tmp/root",
            "source_path": path,
            "source_path_display": path,
            "format": "txt",
            "parser": "txt_plain",
            "fidelity": 5,
            "size_bytes": 1,
            "mtime_ns": time.time_ns(),
            "indexed_at": time.time_ns(),
            "classification": "품의서",
            "summary_oneline": f"요약-{doc_id[-4:]}",
            "summary_paragraph": None,
            "summary_detailed": None,
            "language": None,
            "warnings_json": "[]",
            "metadata_json": "{}",
        }
    )


def test_bm25_only_when_no_endpoints_configured():
    # No monkeypatching — factories return None on empty settings, so
    # the retriever silently falls back to BM25.
    meta = MetaStore()
    fts = FtsStore()
    try:
        _seed(meta, "sha256:" + "a" * 64, "/tmp/a.txt")
        _seed(meta, "sha256:" + "b" * 64, "/tmp/b.txt")
        fts.upsert(
            [
                {
                    "chunk_id": "sha256:" + "a" * 64 + ":0",
                    "doc_id": "sha256:" + "a" * 64,
                    "text": "예산 증액 품의서 초안",
                },
                {
                    "chunk_id": "sha256:" + "b" * 64 + ":0",
                    "doc_id": "sha256:" + "b" * 64,
                    "text": "회의록 요약",
                },
            ]
        )
        results = hybrid_search("예산", top_k=5)
    finally:
        meta.close()
    assert results
    assert results[0]["doc_id"] == "sha256:" + "a" * 64


def test_hybrid_fuses_bm25_and_dense(monkeypatch: pytest.MonkeyPatch):
    meta = MetaStore()
    fts = FtsStore()
    vec = VectorStore()
    try:
        _seed(meta, "sha256:" + "a" * 64, "/tmp/a.txt")
        _seed(meta, "sha256:" + "b" * 64, "/tmp/b.txt")
        fts.upsert(
            [
                {
                    "chunk_id": "sha256:" + "a" * 64 + ":0",
                    "doc_id": "sha256:" + "a" * 64,
                    "text": "계약서 조항 abcxyz",
                },
                {
                    "chunk_id": "sha256:" + "b" * 64 + ":0",
                    "doc_id": "sha256:" + "b" * 64,
                    "text": "완전히 다른 내용 uvwxyz",
                },
            ]
        )
        vec.upsert(
            [
                {
                    "chunk_id": "sha256:" + "a" * 64 + ":0",
                    "doc_id": "sha256:" + "a" * 64,
                    "text": "계약서",
                    "vector": [0.0] * EMBED_DIM,
                },
                {
                    "chunk_id": "sha256:" + "b" * 64 + ":0",
                    "doc_id": "sha256:" + "b" * 64,
                    "text": "회의록",
                    "vector": [1.0] * EMBED_DIM,
                },
            ]
        )

        class _FakeEmbed:
            def embed(self, texts: list[str]) -> list[list[float]]:
                return [[1.0] * EMBED_DIM for _ in texts]

            def close(self) -> None:
                pass

        monkeypatch.setattr(hybrid_mod, "get_embed_client", lambda: _FakeEmbed())
        monkeypatch.setattr(hybrid_mod, "get_rerank_client", lambda: None)

        results = hybrid_search("abcxyz", top_k=5)
    finally:
        meta.close()

    ids = [r["doc_id"] for r in results]
    assert "sha256:" + "a" * 64 in ids
    assert "sha256:" + "b" * 64 in ids


def test_reranker_reorders_when_available(monkeypatch: pytest.MonkeyPatch):
    meta = MetaStore()
    fts = FtsStore()
    try:
        _seed(meta, "sha256:" + "a" * 64, "/tmp/a.txt")
        _seed(meta, "sha256:" + "b" * 64, "/tmp/b.txt")
        fts.upsert(
            [
                {
                    "chunk_id": "sha256:" + "a" * 64 + ":0",
                    "doc_id": "sha256:" + "a" * 64,
                    "text": "예산 초안",
                },
                {
                    "chunk_id": "sha256:" + "b" * 64 + ":0",
                    "doc_id": "sha256:" + "b" * 64,
                    "text": "예산 최종본",
                },
            ]
        )

        class _FakeRerank:
            def rerank(self, query: str, docs: list[str], top_k: int | None = None) -> list[dict[str, Any]]:
                return [{"index": 1, "score": 0.99}, {"index": 0, "score": 0.1}]

            def close(self) -> None:
                pass

        monkeypatch.setattr(hybrid_mod, "get_embed_client", lambda: None)
        monkeypatch.setattr(hybrid_mod, "get_rerank_client", lambda: _FakeRerank())

        results = hybrid_search("예산", top_k=2)
    finally:
        meta.close()

    assert len(results) == 2
    assert results[0]["score"] == 0.99
