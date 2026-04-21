"""RPC-facing search entry point.

Modes:
  * ``mode="search"`` — pure BM25 lexical body search. Zero AI calls.
    This is what the "내용" tab runs: must feel instant, must work
    with no embed/rerank endpoint configured at all.
  * ``mode="ask"``    — hybrid retrieval (BM25 + dense + rerank) feeding
    the strict-provenance RAG answerer. This is the "AI" tab and is
    the only path that touches the embed/rerank/LLM endpoints.

The lexical and hybrid paths share the daemon's ingest output — both
read from the same Tantivy index that `indexer.pipeline.index_file`
writes synchronously at upsert time. That is what keeps the lexical
tab usable the moment a file is parsed, independent of any AI worker.
"""

from __future__ import annotations

from typing import Any

from eoditdeora.api.rpc_server import RpcError
from eoditdeora.retriever.hybrid import hybrid_search
from eoditdeora.retriever.lexical import lexical_search
from eoditdeora.retriever.rag import answer_strict
from eoditdeora.storage.meta import MetaStore
from eoditdeora.storage.history import HistoryStore
from eoditdeora.utils.logging import get_logger

log = get_logger(__name__)


def _index_has_documents() -> bool:
    """Best-effort check for whether any parsed documents exist."""
    try:
        meta = MetaStore()
    except Exception as e:  # noqa: BLE001
        log.warning("search_index_state_probe_failed", error=str(e))
        return True
    try:
        return meta.count_documents() > 0
    except Exception as e:  # noqa: BLE001
        log.warning("search_index_state_probe_failed", error=str(e))
        return True
    finally:
        meta.close()


async def search(query: str, top_k: int = 10, mode: str = "search") -> dict[str, Any]:
    """Top-level search entry point.

    Any unhandled exception bubbling out of a storage backend or model
    client must NOT tear down the RPC loop. The UI receives
    ``results=[]`` plus a structured ``warning`` tag so it can display
    the actual problem without the app window disappearing.
    """
    use_hybrid = mode == "ask"
    if top_k <= 0:
        return {"query": query, "results": []}
    try:
        history = HistoryStore()
        try:
            history.record_query(query)
        finally:
            history.close()
    except Exception as e:  # noqa: BLE001
        log.warning("history_record_query_failed", error=str(e))
    try:
        hits = (
            hybrid_search(query, top_k=top_k)
            if use_hybrid
            else lexical_search(query, top_k=top_k)
        )
    except Exception as e:  # noqa: BLE001
        log.exception(
            "search_backend_failed",
            mode=mode,
            error=str(e),
        )
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
        payload["warning"] = "no_results" if _index_has_documents() else "index_empty"

    if mode == "ask":
        try:
            payload["answer"] = answer_strict(query, hits)
        except RpcError:
            raise
        except Exception as e:  # noqa: BLE001
            log.exception("search_answer_failed", error=str(e))
            payload["answer"] = {
                "answered": False,
                "answer": f"답변 생성 실패: {type(e).__name__}",
                "citations": [],
            }
    return payload
