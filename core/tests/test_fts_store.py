"""Tantivy FTS with Kiwi pre-tokenization."""

from __future__ import annotations

from pathlib import Path

from eoditdeora.storage.fts import FtsStore


def test_upsert_and_search_korean(tmp_path: Path):
    store = FtsStore(index_dir=tmp_path / "tantivy")
    store.upsert(
        [
            {"chunk_id": "c1", "doc_id": "d1", "text": "예산 증액 품의서 초안"},
            {"chunk_id": "c2", "doc_id": "d2", "text": "회의록 요약본"},
            {"chunk_id": "c3", "doc_id": "d3", "text": "계약서 개정안 예산"},
        ]
    )
    results = store.search("예산", top_k=5)
    ids = [r["chunk_id"] for r in results]
    assert "c1" in ids
    assert "c3" in ids
    assert "c2" not in ids


def test_search_ranks_relevant_higher(tmp_path: Path):
    store = FtsStore(index_dir=tmp_path / "tantivy")
    store.upsert(
        [
            {"chunk_id": "a", "doc_id": "d", "text": "예산 예산 예산 증액"},
            {"chunk_id": "b", "doc_id": "d", "text": "예산 한 번 언급"},
        ]
    )
    results = store.search("예산", top_k=5)
    # More occurrences should generally rank first.
    assert results[0]["chunk_id"] == "a"


def test_delete_doc(tmp_path: Path):
    store = FtsStore(index_dir=tmp_path / "tantivy")
    store.upsert(
        [
            {"chunk_id": "c1", "doc_id": "d1", "text": "예산"},
            {"chunk_id": "c2", "doc_id": "d2", "text": "예산"},
        ]
    )
    store.delete_doc("d1")
    ids = [r["chunk_id"] for r in store.search("예산", top_k=5)]
    assert "c1" not in ids
    assert "c2" in ids


def test_upsert_is_idempotent(tmp_path: Path):
    store = FtsStore(index_dir=tmp_path / "tantivy")
    rec = {"chunk_id": "x", "doc_id": "d", "text": "고유 표현 abcxyz"}
    store.upsert([rec])
    store.upsert([rec])
    results = store.search("abcxyz", top_k=10)
    assert len(results) == 1


def test_empty_query_returns_nothing(tmp_path: Path):
    store = FtsStore(index_dir=tmp_path / "tantivy")
    store.upsert([{"chunk_id": "c1", "doc_id": "d1", "text": "내용"}])
    assert store.search("", top_k=5) == []


def test_non_positive_top_k_returns_nothing(tmp_path: Path):
    store = FtsStore(index_dir=tmp_path / "tantivy")
    store.upsert([{"chunk_id": "c1", "doc_id": "d1", "text": "내용"}])
    assert store.search("내용", top_k=0) == []
