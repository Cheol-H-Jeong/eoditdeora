from __future__ import annotations

from pathlib import Path

from eoditdeora.storage.fts import FtsStore


def test_phrase_query_matches_only_adjacent_terms(tmp_path: Path):
    store = FtsStore(index_dir=tmp_path / "tantivy")
    store.upsert(
        [
            {"chunk_id": "c1", "doc_id": "d1", "text": "예산 품의서"},
            {"chunk_id": "c2", "doc_id": "d2", "text": "예산 미리 품의서"},
        ]
    )

    results = store.search('"예산 품의서"', top_k=5)

    assert [r["chunk_id"] for r in results] == ["c1"]


def test_negative_term_excludes_matching_documents(tmp_path: Path):
    store = FtsStore(index_dir=tmp_path / "tantivy")
    store.upsert(
        [
            {"chunk_id": "c1", "doc_id": "d1", "text": "예산 취소"},
            {"chunk_id": "c2", "doc_id": "d2", "text": "예산 승인"},
        ]
    )

    results = store.search("예산 -취소", top_k=5)

    assert [r["chunk_id"] for r in results] == ["c2"]


def test_negative_phrase_excludes_only_exact_phrase(tmp_path: Path):
    store = FtsStore(index_dir=tmp_path / "tantivy")
    store.upsert(
        [
            {"chunk_id": "c1", "doc_id": "d1", "text": "예산 품의서 초안 검토"},
            {"chunk_id": "c2", "doc_id": "d2", "text": "예산 초안 품의서 검토"},
            {"chunk_id": "c3", "doc_id": "d3", "text": "예산 승인 완료"},
        ]
    )

    results = store.search('예산 -"품의서 초안"', top_k=5)

    assert {r["chunk_id"] for r in results} == {"c2", "c3"}
