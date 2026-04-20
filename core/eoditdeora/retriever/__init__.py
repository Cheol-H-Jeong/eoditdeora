"""Hybrid retriever and RAG answerer.

- `hybrid_search()` fuses BM25 (Tantivy) and dense (LanceDB) candidates,
  reranks with bge-reranker-v2-m3, and returns ranked hits with
  doc metadata populated from SQLite.
- `answer_strict()` builds a strict-provenance prompt from the top hits
  and sends it to the LLM, returning answer text + citation map.
"""

from eoditdeora.retriever.hybrid import hybrid_search
from eoditdeora.retriever.rag import answer_strict

__all__ = ["answer_strict", "hybrid_search"]
