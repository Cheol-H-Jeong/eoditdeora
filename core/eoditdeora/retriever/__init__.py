"""Hybrid retriever and RAG answerer.

- `hybrid_search()` fuses BM25 (Tantivy) and dense (LanceDB) candidates,
  reranks with bge-reranker-v2-m3, and returns ranked hits with
  doc metadata populated from SQLite.
- `answer_strict()` builds a strict-provenance prompt from the top hits
  and sends it to the LLM, returning answer text + citation map.
"""

from __future__ import annotations

from typing import Any

__all__ = ["answer_strict", "hybrid_search"]


def hybrid_search(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
    from eoditdeora.retriever.hybrid import hybrid_search as _hybrid_search

    return _hybrid_search(*args, **kwargs)


def answer_strict(*args: Any, **kwargs: Any) -> dict[str, Any]:
    from eoditdeora.retriever.rag import answer_strict as _answer_strict

    return _answer_strict(*args, **kwargs)
