"""RPC-facing search entry point."""

from __future__ import annotations

from typing import Any

from eoditdeora.retriever.hybrid import hybrid_search
from eoditdeora.retriever.rag import answer_strict
from eoditdeora.utils.logging import get_logger

log = get_logger(__name__)


async def search(query: str, top_k: int = 10, mode: str = "search") -> dict[str, Any]:
    """Top-level search entry point.

    Wraps `hybrid_search` with defense in depth: any unhandled exception
    bubbling out of a storage backend or model client must NOT tear
    down the RPC loop. The UI receives `results=[]` plus a structured
    `warning` tag so it can display the actual problem without the app
    window disappearing.
    """
    try:
        hits = hybrid_search(query, top_k=top_k)
    except Exception as e:  # noqa: BLE001
        log.exception("search_hybrid_failed", error=str(e))
        return {
            "query": query,
            "results": [],
            "warning": "search_backend_failed",
            "detail": f"{type(e).__name__}: {e}",
        }

    payload: dict[str, Any] = {"query": query, "results": hits}
    if not hits:
        # Distinguish "no matches" from "backend reported nothing because
        # the index is empty". The UI uses this to prompt the user to
        # add a root / wait for indexing to catch up.
        payload["warning"] = "no_results"

    if mode == "ask":
        try:
            payload["answer"] = answer_strict(query, hits)
        except Exception as e:  # noqa: BLE001
            log.exception("search_answer_failed", error=str(e))
            payload["answer"] = {
                "answered": False,
                "answer": f"답변 생성 실패: {type(e).__name__}",
                "citations": [],
            }
    return payload
