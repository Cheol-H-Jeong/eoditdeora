"""LanceDB vector store."""

from __future__ import annotations

from pathlib import Path

from eoditdeora.storage.vectors import EMBED_DIM, VectorStore


def _vec(seed: float) -> list[float]:
    # deterministic filler vector
    return [seed + i * 1e-4 for i in range(EMBED_DIM)]


def test_upsert_and_search(tmp_path: Path):
    store = VectorStore(db_dir=tmp_path / "lance")
    store.upsert(
        [
            {"chunk_id": "c1", "doc_id": "d1", "text": "첫 청크", "vector": _vec(0.1)},
            {"chunk_id": "c2", "doc_id": "d1", "text": "둘째 청크", "vector": _vec(0.2)},
        ]
    )
    hits = store.search(_vec(0.1), top_k=2)
    assert len(hits) == 2
    ids = [h["chunk_id"] for h in hits]
    assert "c1" in ids


def test_upsert_is_idempotent(tmp_path: Path):
    store = VectorStore(db_dir=tmp_path / "lance")
    rec = {"chunk_id": "c1", "doc_id": "d1", "text": "내용", "vector": _vec(0.5)}
    store.upsert([rec])
    store.upsert([rec])  # second call should replace, not duplicate
    hits = store.search(_vec(0.5), top_k=10)
    assert len([h for h in hits if h["chunk_id"] == "c1"]) == 1


def test_delete_doc_removes_all_chunks(tmp_path: Path):
    store = VectorStore(db_dir=tmp_path / "lance")
    store.upsert(
        [
            {"chunk_id": "c1", "doc_id": "d1", "text": "a", "vector": _vec(0.1)},
            {"chunk_id": "c2", "doc_id": "d1", "text": "b", "vector": _vec(0.2)},
            {"chunk_id": "c3", "doc_id": "d2", "text": "c", "vector": _vec(0.3)},
        ]
    )
    store.delete_doc("d1")
    hits = store.search(_vec(0.15), top_k=10)
    ids = [h["chunk_id"] for h in hits]
    assert "c1" not in ids
    assert "c2" not in ids
    assert "c3" in ids


def test_empty_upsert_is_noop(tmp_path: Path):
    store = VectorStore(db_dir=tmp_path / "lance")
    store.upsert([])  # must not crash
    assert store.search(_vec(0.0), top_k=5) == []
