"""RPC-facing search entry point."""

from __future__ import annotations

from typing import Any

from eoditdeora.retriever.hybrid import hybrid_search
from eoditdeora.retriever.rag import answer_strict
from eoditdeora.utils.logging import get_logger

log = get_logger(__name__)


async def search(query: str, top_k: int = 10, mode: str = "search") -> dict[str, Any]:
    hits = hybrid_search(query, top_k=top_k)
    if mode == "ask":
        answer = answer_strict(query, hits)
        return {"query": query, "results": hits, "answer": answer}
    return {"query": query, "results": hits}
